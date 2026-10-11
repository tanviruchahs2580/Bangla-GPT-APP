"""TST-04 (AUD-0006): exercise the school routes the isolation suite did not.

The two-tenant suite covered the six dashboard routes. These tests cover the
remaining uncovered blocks - /school/classes, /school/coverage,
/school/analytics and the invite lifecycle - including the empty-tenant paths,
which is where most of the missed branches were: an analytics call for a school
with no students skips the whole aggregation block, and a class with no graded
attempts divides by nothing.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JOIN_PASSWORD = "joinsecret9"


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/school.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/school.db")
    yield client, conn
    conn.close()


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def _root(client: TestClient) -> dict:
    return _login(client, "root@example.com")


def _invite(client: TestClient, headers: dict, school_id: int, role: str) -> str:
    res = client.post(f"/schools/{school_id}/invites", json={"role": role}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["code"]


def _join(client: TestClient, code: str, email: str) -> None:
    res = client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": JOIN_PASSWORD, "name": "Staff"},
    )
    assert res.status_code == 201, res.text


def _school_with_staff(client: TestClient, name: str, email: str) -> dict:
    """A school with a principal (school_admin, who may read /school/*) and a
    teacher (who may create classrooms and enrol pupils)."""
    root = _root(client)
    school = client.post("/admin/schools", json={"name": name}, headers=root).json()
    sid = school["id"]

    _join(client, _invite(client, root, sid, "school_admin"), email)
    principal = _login(client, email, JOIN_PASSWORD)

    teacher_email = email.replace("@", ".teacher@")
    _join(client, _invite(client, root, sid, "teacher"), teacher_email)
    teacher = _login(client, teacher_email, JOIN_PASSWORD)
    room = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teacher).json()

    return {
        "school": school,
        "principal": principal,
        "teacher": teacher,
        "room_id": room["id"],
    }


def _enrol(client: TestClient, teacher: dict, room_id: int, names: list[str]) -> None:
    csv_text = "\n".join(f"{n},{n.split()[0].lower()}@stu.test" for n in names)
    res = client.post(
        f"/teacher/classrooms/{room_id}/import",
        json={"csv_text": csv_text},
        headers=teacher,
    )
    assert res.status_code == 200, res.text


# --------------------------------------------------------- /school/classes ---
def test_classes_lists_every_room_even_with_no_students(env):
    client, _ = env
    ctx = _school_with_staff(client, "Classes School", "t@classes.test")
    rows = client.get("/school/classes", headers=ctx["principal"]).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["classroom_id"] == ctx["room_id"]
    assert row["students"] == 0
    assert row["quiz_attempts"] == 0
    assert row["attempts_graded"] == 0
    # An empty room must report an honest zero accuracy, not a crash.
    assert row["avg_quiz_accuracy"] in (None, 0)


def test_classes_counts_enrolled_students(env):
    client, _ = env
    ctx = _school_with_staff(client, "Enrol School", "t@enrol.test")
    _enrol(client, ctx["teacher"], ctx["room_id"], ["Ada Lovelace", "Alan Turing"])
    rows = client.get("/school/classes", headers=ctx["principal"]).json()
    assert rows[0]["students"] == 2


def test_classes_is_scoped_to_the_callers_school(env):
    client, _ = env
    a = _school_with_staff(client, "School A", "t@a.test")
    b = _school_with_staff(client, "School B", "t@b.test")
    _enrol(client, a["teacher"], a["room_id"], ["Solo Student"])
    mine = client.get("/school/classes", headers=a["principal"]).json()
    assert mine[0]["students"] == 1
    theirs = client.get("/school/classes", headers=b["principal"]).json()
    assert theirs[0]["students"] == 0


def test_classes_rejects_a_school_the_caller_does_not_belong_to(env):
    client, _ = env
    a = _school_with_staff(client, "Owner A", "t@owner-a.test")
    b = _school_with_staff(client, "Owner B", "t@owner-b.test")
    res = client.get(f"/school/classes?school_id={b['school']['id']}", headers=a["principal"])
    assert res.status_code in (403, 404)


# -------------------------------------------------------- /school/coverage ---
def test_coverage_reports_no_signal_for_an_empty_school(env):
    client, _ = env
    ctx = _school_with_staff(client, "Empty Coverage", "t@emptycov.test")
    res = client.get("/school/coverage", headers=ctx["principal"])
    assert res.status_code == 200, res.text
    body = res.json()
    # The grade the school runs is reported, but with honest emptiness inside
    # it: no subjects covered, no chapters read, and never a false "covered".
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["class_level"] == 6
    assert row["content_subjects"] == []
    assert row["asked_subjects"] == []
    assert row["uncovered_subjects"] == []


def test_coverage_is_scoped_to_the_callers_school(env):
    client, _ = env
    a = _school_with_staff(client, "Cov A", "t@cova.test")
    b = _school_with_staff(client, "Cov B", "t@covb.test")
    assert client.get("/school/coverage", headers=a["principal"]).status_code == 200
    assert client.get("/school/coverage", headers=b["principal"]).status_code == 200
    res = client.get(f"/school/coverage?school_id={b['school']['id']}", headers=a["principal"])
    assert res.status_code in (403, 404)


# -------------------------------------------------------- /school/analytics ---
def test_analytics_with_no_students_returns_zeros_not_an_error(env):
    client, _ = env
    ctx = _school_with_staff(client, "Empty Analytics", "t@emptyan.test")
    res = client.get("/school/analytics", headers=ctx["principal"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["active_by_date"] == []
    assert body["questions_asked"] == 0
    assert body["quiz_attempts"] == 0
    assert body["attempts_graded"] == 0
    assert body["avg_quiz_score_pct"] is None


def test_analytics_aggregates_after_students_are_enrolled(env):
    client, conn = env
    ctx = _school_with_staff(client, "Busy Analytics", "t@busy.test")
    _enrol(client, ctx["teacher"], ctx["room_id"], ["Grace Hopper"])
    res = client.get("/school/analytics", headers=ctx["principal"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["questions_asked"] == 0  # no chat turns yet
    assert body["quiz_attempts"] == 0
    assert body["avg_quiz_score_pct"] is None


def test_analytics_window_is_validated(env):
    client, _ = env
    ctx = _school_with_staff(client, "Window School", "t@window.test")
    assert client.get("/school/analytics?days=0", headers=ctx["principal"]).status_code == 422
    assert client.get("/school/analytics?days=91", headers=ctx["principal"]).status_code == 422
    assert client.get("/school/analytics?days=7", headers=ctx["principal"]).status_code == 200


def test_analytics_is_scoped_to_the_callers_school(env):
    client, _ = env
    a = _school_with_staff(client, "An A", "t@ana.test")
    b = _school_with_staff(client, "An B", "t@anb.test")
    _enrol(client, a["teacher"], a["room_id"], ["Student One"])
    theirs = client.get("/school/analytics", headers=b["principal"]).json()
    # A's activity must never surface in B's analytics.
    assert theirs["active_by_date"] == []
    assert theirs["quiz_attempts"] == 0
    res = client.get(f"/school/analytics?school_id={b['school']['id']}", headers=a["principal"])
    assert res.status_code in (403, 404)


# ------------------------------------------------------- invite lifecycle ---
def test_invite_list_shows_expiry_and_revoke_removes_it(env):
    client, _ = env
    root = _root(client)
    school = client.post("/admin/schools", json={"name": "Invites"}, headers=root).json()
    code = _invite(client, root, school["id"], "teacher")

    listed = client.get(f"/admin/schools/{school['id']}/invites", headers=root).json()
    assert len(listed) == 1
    assert listed[0]["expires_at"] is not None
    assert listed[0]["used"] is False

    revoked = client.delete(
        f"/admin/schools/{school['id']}/invites/{listed[0]['id']}", headers=root
    )
    assert revoked.status_code == 204
    assert client.get(f"/admin/schools/{school['id']}/invites", headers=root).json() == []
    # A revoked code cannot be redeemed.
    res = client.post(
        "/auth/join-school",
        json={
            "invite_code": code,
            "email": "gone@inv.test",
            "password": JOIN_PASSWORD,
            "name": "Gone",
        },
    )
    assert res.status_code == 404


def test_revoking_a_redeemed_invite_is_refused(env):
    client, _ = env
    root = _root(client)
    school = client.post("/admin/schools", json={"name": "Used"}, headers=root).json()
    _join(client, _invite(client, root, school["id"], "teacher"), "kept@used.test")
    listed = client.get(f"/admin/schools/{school['id']}/invites", headers=root).json()
    assert listed[0]["used"] is True
    res = client.delete(f"/admin/schools/{school['id']}/invites/{listed[0]['id']}", headers=root)
    assert res.status_code in (400, 409)


def test_invite_list_for_an_unknown_school_is_404(env):
    client, _ = env
    assert client.get("/admin/schools/99999/invites", headers=_root(client)).status_code == 404
