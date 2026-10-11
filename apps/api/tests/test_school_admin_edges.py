"""TST-04 (AUD-0006), third suite: admin fallbacks and tenant guards.

The two prior suites exercise the school_admin happy path and the
"there is data" aggregation branches. This suite covers the remaining
decision points:

* platform ``admin`` (no ``school_id``) hitting ``/schools/mine``,
  ``/school/overview`` and ``/school/*`` falls back to the default school;
* a ``school_admin`` whose ``school_id`` is NULL is a provisioning error and
  gets an honest 404 rather than silently reading the default school;
* empty-collection guards (no rooms / no staff / no class_teachers) return
  honest zeros instead of crashing;
* ``/school/students?class_level=`` filters, and ``last_active`` is the
  newer of the last activity day and the last quiz attempt.

Each fallback/guard is asserted on its observable output so a regression in
the branch is caught, not just an executed line.
"""

import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.auth.security import create_access_token, hash_password
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JOIN_PASSWORD = "joinsecret9"


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/edge.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/edge.db")
    yield client, conn, settings
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


def _join(client: TestClient, code: str, email: str) -> dict:
    res = client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": JOIN_PASSWORD, "name": "Staff"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _seed_user(conn, settings, email: str, role: str, school_id: int | None) -> dict:
    """Insert a user directly (to control school_id) and mint a token for it.

    Seeding through the ORM keeps password hashing and token minting identical
    to the real login path; only the school_id (which no public endpoint can
    set to NULL for an existing account) is forced by the fixture.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from bangla_gpt_api.db.models import User

    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    with Session(engine) as db:
        u = User(
            email=email,
            password_hash=hash_password(PASSWORD),
            role=role,
            school_id=school_id,
            email_verified=True,
            must_change_password=False,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        token = create_access_token(u, settings=settings)
        return {"Authorization": "Bearer " + token}


# ---------------------------------------------- platform admin -> default ---
def test_platform_admin_mine_falls_back_to_default_school(env):
    client, _, _ = env
    body = client.get("/schools/mine", headers=_root(client))
    assert body.status_code == 200, body.text
    # No school_id on the admin account -> the shared default school is used.
    assert body.json()["name"] == "Default School"


def test_platform_admin_overview_falls_back_to_default_school(env):
    client, _, _ = env
    res = client.get("/school/overview", headers=_root(client))
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Default School"
    # Default school has no classrooms/students: honest zeros, no crash.
    body = res.json()
    assert body["classrooms"] == 0
    assert body["students"] == 0
    assert body["strong"] == 0 and body["risk"] == 0 and body["ungraded"] == 0


def test_platform_admin_school_sections_fall_back_to_default_school(env):
    client, _, _ = env
    root = _root(client)
    assert client.get("/school/students", headers=root).json()["total"] == 0
    assert client.get("/school/classes", headers=root).json() == []
    assert client.get("/school/teachers", headers=root).json() == []
    assert client.get("/school/analytics", headers=root).json()["questions_asked"] == 0


# -------------------------------- school_admin with NULL school is 404 ----
def test_school_admin_without_school_is_404_not_default(env):
    client, conn, settings = env
    headers = _seed_user(conn, settings, "orphan@example.com", "school_admin", None)
    mine = client.get("/schools/mine", headers=headers)
    assert mine.status_code == 404, mine.text
    assert mine.json()["detail"]["code"] == "no_school"

    overview = client.get("/school/overview", headers=headers)
    assert overview.status_code == 404, overview.text


def test_school_admin_without_school_404s_on_school_sections(env):
    client, conn, settings = env
    headers = _seed_user(conn, settings, "orphan2@example.com", "school_admin", None)
    # /school/* resolves through _actor_school, which also refuses rather than
    # leaking the default school to an unprovisioned account.
    for path in ("/school/students", "/school/classes", "/school/teachers"):
        assert client.get(path, headers=headers).status_code == 404, path


# ------------------------------------------------ empty-collection guards ---
def test_school_overview_for_school_with_no_rooms(env):
    client, conn, settings = env
    root = _root(client)
    school = client.post("/admin/schools", json={"name": "Roomless"}, headers=root).json()
    admin = _seed_user(conn, settings, "head@roomless.test", "school_admin", school["id"])
    res = client.get("/school/overview", headers=admin)
    assert res.status_code == 200, res.text
    body = res.json()
    # no rooms -> the student-count aggregation is skipped, not divided by zero
    assert body["classrooms"] == 0
    assert body["students"] == 0
    assert body["sessions_7d"] == 0


def test_school_mine_counts_staff_with_no_assignments(env):
    client, conn, settings = env
    root = _root(client)
    school = client.post("/admin/schools", json={"name": "Unassigned"}, headers=root).json()
    # principal exists (a staff profile) but has zero classroom assignments.
    code = _invite(client, root, school["id"], "school_admin")
    _join(client, code, "solo@unassigned.test")
    principal = _login(client, "solo@unassigned.test", JOIN_PASSWORD)
    mine = client.get("/schools/mine", headers=principal)
    assert mine.status_code == 200, mine.text
    assert mine.json()["teachers"] == 1
    assert mine.json()["staff"][0]["classroom_count"] == 0


def test_school_teachers_reports_subject_assignments(env):
    client, conn, settings = env
    root = _root(client)
    school = client.post("/admin/schools", json={"name": "Assigned"}, headers=root).json()
    sid = school["id"]
    _join(client, _invite(client, root, sid, "school_admin"), "pa@assigned.test")
    teacher_code = _invite(client, root, sid, "teacher")
    _join(client, teacher_code, "ta@assigned.test")
    teacher = _login(client, "ta@assigned.test", JOIN_PASSWORD)
    room = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teacher).json()

    # Seed a class_teachers assignment (subject-specific) for the teacher.
    t_id = conn.execute(
        "SELECT t.id FROM teachers t JOIN users u ON u.id = t.user_id WHERE u.email = ?",
        ("ta@assigned.test",),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO class_teachers (classroom_id, teacher_id, subject, created_at)"
        " VALUES (?, ?, ?, ?)",
        (room["id"], t_id, "math", datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")),
    )
    conn.commit()

    principal = _login(client, "pa@assigned.test", JOIN_PASSWORD)
    rows = client.get("/school/teachers", headers=principal).json()
    by_email = {r["name"]: r for r in rows}
    assigned = next(r for r in rows if r["teacher_id"] == t_id)
    assert assigned["subjects"] == ["math"]
    assert assigned["classrooms"] == 1
    assert by_email  # both staff present


# ------------------------------------------- /school/students filters -----
def _school_with_students(client, conn, name: str, principal: str, teacher: str):
    root = _root(client)
    school = client.post("/admin/schools", json={"name": name}, headers=root).json()
    sid = school["id"]
    _join(client, _invite(client, root, sid, "school_admin"), principal)
    _join(client, _invite(client, root, sid, "teacher"), teacher)
    teacher_h = _login(client, teacher, JOIN_PASSWORD)
    room6 = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teacher_h).json()
    room7 = client.post(
        "/teacher/classrooms", json={"class_level": 7, "section": "B"}, headers=teacher_h
    ).json()
    csv = "Grade Six,g6@stu.test\nGrade Seven,g7@stu.test"
    imported = client.post(
        f"/teacher/classrooms/{room6['id']}/import",
        json={"csv_text": csv},
        headers=teacher_h,
    )
    assert imported.status_code == 200, imported.text
    return {
        "school": school,
        "principal": _login(client, principal, JOIN_PASSWORD),
        "room6": room6,
        "room7": room7,
    }


def _student_id(conn, email: str) -> int:
    row = conn.execute(
        "SELECT s.id FROM students s JOIN users u ON u.id = s.user_id WHERE u.email = ?",
        (email,),
    ).fetchone()
    assert row is not None, email
    return int(row[0])


def test_students_filters_by_class_level(env):
    client, conn, _ = env
    ctx = _school_with_students(client, conn, "Filter School", "p@filter.test", "t@filter.test")
    six = _student_id(conn, "g6@stu.test")
    seven = _student_id(conn, "g7@stu.test")
    # Both pupils are imported into the grade-6 room, so their students.class_level
    # is 6. Move the second pupil to grade 7 at the Student level (which is what
    # the endpoint filters on) to give the filter two distinct grades to work with.
    conn.execute("UPDATE students SET class_level = 7 WHERE id = ?", (seven,))
    conn.commit()

    page6 = client.get("/school/students?class_level=6", headers=ctx["principal"]).json()
    ids6 = {r["student_id"] for r in page6["items"]}
    assert ids6 == {six}
    assert page6["total"] == 1

    page7 = client.get("/school/students?class_level=7", headers=ctx["principal"]).json()
    ids7 = {r["student_id"] for r in page7["items"]}
    assert ids7 == {seven}


def test_students_last_active_prefers_newer_activity_over_attempt(env):
    client, conn, _ = env
    ctx = _school_with_students(client, conn, "Merge School", "p@merge.test", "t@merge.test")
    sid = _student_id(conn, "g6@stu.test")

    # A quiz attempt dated in the past.
    conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total,"
        " correct, score_pct, quiz_json, created_at)"
        " VALUES (?, 'math', 6, 'graded', 10, 8, 80.0, '[]', ?)",
        (sid, "2020-01-02 10:00:00"),
    )
    # Daily activity dated today (newer) must win.
    conn.execute(
        "INSERT INTO daily_activity (student_id, date, questions, quizzes, minutes)"
        " VALUES (?, date('now'), 5, 0, 5)",
        (sid,),
    )
    conn.commit()

    row = client.get("/school/students", headers=ctx["principal"]).json()["items"][0]
    assert row["last_active"] is not None
    assert not row["last_active"].startswith("2020-01-02"), "activity day should beat old attempt"


def test_students_last_active_uses_attempt_when_no_activity(env):
    client, conn, _ = env
    ctx = _school_with_students(client, conn, "Attempt School", "p@att.test", "t@att.test")
    sid = _student_id(conn, "g6@stu.test")
    conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total,"
        " correct, score_pct, quiz_json, created_at)"
        " VALUES (?, 'math', 6, 'graded', 10, 8, 80.0, '[]', '2021-05-06 12:00:00')",
        (sid,),
    )
    conn.commit()
    row = client.get("/school/students", headers=ctx["principal"]).json()["items"][0]
    assert row["last_active"] == "2021-05-06"
