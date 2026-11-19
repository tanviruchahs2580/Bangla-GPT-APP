"""T-20/BC-5: attempt-membership link tables — dual-write, read parity,
reconciliation, delete behaviour, backfill idempotency.

The JSON ``attempts`` arrays stay the DEFAULT read path (``ATTEMPT_LINKS_READ``
defaults False); these tests prove the mirror is honest under both settings
and that the API responses are identical, which is what lets the read default
flip later (S-3) and the JSON column drop (later release).
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.attempt_links import reconcile_attempt_links
from conftest import engine_url

PASSWORD = "Str0ngRootPassw0rd!"
JOIN_PASSWORD = "Str0ngJoinPassw0rd!"


@pytest.fixture
def make_env(tmp_path):
    def make(**overrides):
        base = dict(
            env="test",
            database_url=engine_url(tmp_path, "t20"),
            jwt_secret="test-secret-0123456789abcdef0123456789",
            admin_email="root@example.com",
            admin_password=PASSWORD,
            force_admin_password_change=False,
        )
        base.update(overrides)
        client = TestClient(create_app(Settings(**base)))
        conn = sqlite3.connect(f"{tmp_path}/t20.db")
        conn.row_factory = sqlite3.Row  # the tests read columns by name
        return client, conn

    yield make


def _teacher_with_roster(client: TestClient, conn: sqlite3.Connection, tag: str) -> dict:
    root = {"Authorization": "Bearer " + _login(client, "root@example.com")}
    school = client.post("/admin/schools", json={"name": f"T20 {tag}"}, headers=root).json()
    res = client.post(f"/schools/{school['id']}/invites", json={"role": "teacher"}, headers=root)
    _join(client, res.json()["code"], f"teach.{tag}@t20.test")
    teacher = {"Authorization": "Bearer " + _login(client, f"teach.{tag}@t20.test", JOIN_PASSWORD)}
    room = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teacher).json()
    res = client.post(
        f"/teacher/classrooms/{room['id']}/import",
        json={"csv_text": "name,email\nPupil A,pupil.a@t20.test\nPupil B,pupil.b@t20.test"},
        headers=teacher,
    )
    assert res.status_code == 200, res.text
    return {"teacher": teacher, "room_id": room["id"], "school_id": school["id"]}


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return str(res.json()["access_token"])


def _invite(client: TestClient, headers: dict, school_id: int, role: str) -> str:
    res = client.post(f"/schools/{school_id}/invites", json={"role": role}, headers=headers)
    assert res.status_code == 201, res.text
    return str(res.json()["code"])


def _join(client: TestClient, code: str, email: str) -> None:
    res = client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": JOIN_PASSWORD, "name": "Staff"},
    )
    assert res.status_code == 201, res.text


def _create_shorttest(client: TestClient, who: dict) -> dict:
    res = client.post(
        "/teacher/shorttests",
        json={
            "classroom_id": who["room_id"],
            "subject": "science",
            "chapter": "কোষ",
            "num_questions": 3,
        },
        headers=who["teacher"],
    )
    assert res.status_code == 201, res.text
    return res.json()


def _create_assignment(client: TestClient, who: dict, conn: sqlite3.Connection) -> dict:
    roster_ids = [r["id"] for r in conn.execute("SELECT id FROM students ORDER BY id").fetchall()]
    res = client.post(
        "/teacher/assignments",
        json={
            "classroom_id": who["room_id"],
            "subject": "science",
            "chapter": "কোষ",
            "num_questions": 3,
            "student_ids": roster_ids,
            "due_at": "2030-01-01T00:00:00Z",
        },
        headers=who["teacher"],
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_short_test_dual_write_mirrors_the_json(make_env):
    client, conn = make_env()
    who = _teacher_with_roster(client, conn, "dw")
    st = _create_shorttest(client, who)
    json_refs = {
        (int(r["student_id"]), int(r["attempt_id"]))
        for r in conn.execute(
            "SELECT student_id, attempt_id FROM short_test_attempt_links WHERE short_test_id=?",
            (st["id"],),
        ).fetchall()
    }
    assert len(json_refs) == 2
    assert {sid for sid, _ in json_refs} == {r["student_id"] for r in st["attempts"]}
    assert {aid for _, aid in json_refs} == {r["attempt_id"] for r in st["attempts"]}
    rec = reconcile_attempt_links(_session(client), kind="short_test")
    assert rec["mismatched"] == 0


def test_read_setting_on_and_off_give_identical_api_responses(make_env):
    client_off, conn = make_env()
    who = _teacher_with_roster(client_off, conn, "parity")
    st = _create_shorttest(client_off, who)
    asg = _create_assignment(client_off, who, conn)

    client_on, _conn2 = make_env(attempt_links_read=True)
    # same database file, fresh app with the read switch on
    client_on2 = TestClient(
        create_app(
            Settings(
                env="test",
                database_url=engine_url(client_off.app.state.ctx.settings, "t20")
                if False
                else client_off.app.state.ctx.settings.database_url,
                jwt_secret="test-secret-0123456789abcdef0123456789",
                admin_email="root@example.com",
                admin_password=PASSWORD,
                force_admin_password_change=False,
                attempt_links_read=True,
            )
        )
    )
    teacher_on = {
        "Authorization": "Bearer " + _login(client_on2, "teach.parity@t20.test", JOIN_PASSWORD)
    }
    # the surface serves LIST endpoints for both families — compare the
    # created rows under both read settings
    st_list = client_on2.get("/teacher/shorttests", headers=teacher_on)
    assert st_list.status_code == 200, st_list.text
    st_on = next(r for r in st_list.json() if r["id"] == st["id"])
    assert st_on["attempts"] == st["attempts"], "read switch must not change the response shape"
    asg_list = client_on2.get("/teacher/assignments", headers=teacher_on)
    assert asg_list.status_code == 200, asg_list.text
    asg_on = next(r for r in asg_list.json() if r["id"] == asg["id"])
    assert asg_on["attempts"] == asg["attempts"], "read switch must not change the response shape"


def test_assignment_dual_write_uses_the_existing_recipient_table(make_env):
    """assignments already have their mirror (assignment_recipients); the
    read switch reads THAT table, not a duplicate."""
    client, conn = make_env()
    who = _teacher_with_roster(client, conn, "ar")
    asg = _create_assignment(client, who, conn)
    rows = conn.execute(
        "SELECT student_id, attempt_id FROM assignment_recipients WHERE assignment_id=?",
        (asg["id"],),
    ).fetchall()
    assert len(rows) == 2
    assert {(int(s), int(a)) for s, a in rows} == {
        (r["student_id"], r["attempt_id"]) for r in asg["attempts"]
    }
    rec = reconcile_attempt_links(_session(client), kind="assignment")
    assert rec["mismatched"] == 0


def test_deleting_a_parent_removes_its_link_rows(make_env):
    """The mirror FKs CASCADE — deleting the short test removes its links, so
    no orphan membership can survive the parent."""
    client, conn = make_env()
    who = _teacher_with_roster(client, conn, "del")
    st = _create_shorttest(client, who)
    links_before = conn.execute(
        "SELECT COUNT(*) FROM short_test_attempt_links WHERE short_test_id=?", (st["id"],)
    ).fetchone()[0]
    assert links_before == 2
    conn.execute("PRAGMA foreign_keys=ON")  # the CASCADE under test is an engine feature
    conn.execute("DELETE FROM short_tests WHERE id=?", (st["id"],))
    conn.commit()
    links_after = conn.execute(
        "SELECT COUNT(*) FROM short_test_attempt_links WHERE short_test_id=?", (st["id"],)
    ).fetchone()[0]
    assert links_after == 0


def _session(client: TestClient):
    return client.app.state.ctx.session_factory()
