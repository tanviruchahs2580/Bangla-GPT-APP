"""Wave 1 (BUG-4): delete_me must clean every new FK-bearing table.

analytics_events has no FK by design (append-only, PII-free trail), so its
rows intentionally survive account deletion; that is asserted too.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = chr(0x995) + chr(0x9CB) + chr(0x9B7)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "del.db"


@pytest.fixture
def client(db_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{db_path}",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str) -> dict:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Person", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}", "email": email}


def _user_id(db_path, email: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        conn.close()


def _count(db_path, sql: str, params: tuple = ()) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute(sql, params).fetchone()[0])
    finally:
        conn.close()


def _seed_waves(client: TestClient, headers: dict) -> None:
    """One row in each new table for this account."""
    doc = {"class_level": 6, "subject": "science", "chapter": CHAPTER}
    assert client.post("/teacher/generate/worksheet", json=doc, headers=headers).status_code == 201
    assert client.post("/notes", json={"body": "a note"}, headers=headers).status_code == 201
    # background job row (the run may or may not finish before the portal
    # closes, so assertions below are written for either outcome)
    assert (
        client.post(
            "/teacher/jobs", json={"kind": "worksheet", "payload": doc}, headers=headers
        ).status_code
        == 202
    )
    assert client.post("/events", json={"name": "wave1_seed"}, headers=headers).status_code == 202


def test_delete_me_cleans_all_new_tables(client: TestClient, db_path) -> None:
    teach = _register(client, "teach@example.com", "teacher")
    headers = {"Authorization": teach["Authorization"]}
    _seed_waves(client, headers)

    # direct insert so the teacher also owns a notification row
    uid = _user_id(db_path, "teach@example.com")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO notifications (user_id, kind, code, params, link, read_at, created_at)"
        " VALUES (?, 'system', 'notif_seed', '{}', NULL, NULL, datetime('now'))",
        (uid,),
    )
    # wave-1 columns are real, writable columns
    conn.execute("UPDATE teachers SET prefs = ? WHERE user_id = ?", ('{"ui":"compact"}', uid))
    conn.commit()
    conn.close()

    assert (
        _count(db_path, "SELECT COUNT(*) FROM teacher_documents WHERE teacher_id = ?", (uid,)) >= 1
    )
    assert _count(db_path, "SELECT COUNT(*) FROM saved_notes WHERE user_id = ?", (uid,)) == 1
    assert _count(db_path, "SELECT COUNT(*) FROM ai_jobs WHERE user_id = ?", (uid,)) == 1
    assert _count(db_path, "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid,)) == 1

    assert client.delete("/users/me", headers=headers).status_code == 204

    assert _count(db_path, "SELECT COUNT(*) FROM users WHERE id = ?", (uid,)) == 0
    assert (
        _count(db_path, "SELECT COUNT(*) FROM teacher_documents WHERE teacher_id = ?", (uid,)) == 0
    )
    assert _count(db_path, "SELECT COUNT(*) FROM saved_notes WHERE user_id = ?", (uid,)) == 0
    assert _count(db_path, "SELECT COUNT(*) FROM ai_jobs WHERE user_id = ?", (uid,)) == 0
    assert _count(db_path, "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid,)) == 0
    assert _count(db_path, "SELECT COUNT(*) FROM teachers WHERE user_id = ?", (uid,)) == 0
    # analytics_events deliberately has no FK: the trail survives deletion
    assert (
        _count(
            db_path,
            "SELECT COUNT(*) FROM analytics_events WHERE user_id = ? AND name = 'wave1_seed'",
            (uid,),
        )
        == 1
    )


def test_delete_me_cleans_student_new_rows(client: TestClient, db_path) -> None:
    kid = _register(client, "kid@example.com", "student")
    headers = {"Authorization": kid["Authorization"]}
    assert client.post("/notes", json={"body": "revision list"}, headers=headers).status_code == 201
    assert client.post("/events", json={"name": "study_done"}, headers=headers).status_code == 202

    uid = _user_id(db_path, "kid@example.com")
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT id FROM students WHERE user_id = ?", (uid,)).fetchone()
    assert row is not None
    student_id = int(row[0])
    conn.execute(
        "UPDATE students SET learning_prefs = ?, memory_enabled = 0 WHERE id = ?",
        ('{"pace":"slow"}', student_id),
    )
    conn.execute(
        "INSERT INTO notifications (user_id, kind, code, params, link, read_at, created_at)"
        " VALUES (?, 'system', 'notif_seed', '{}', NULL, NULL, datetime('now'))",
        (uid,),
    )
    conn.commit()
    conn.close()
    assert client.delete("/users/me", headers=headers).status_code == 204

    assert _count(db_path, "SELECT COUNT(*) FROM users WHERE id = ?", (uid,)) == 0
    assert _count(db_path, "SELECT COUNT(*) FROM students WHERE id = ?", (student_id,)) == 0
    assert _count(db_path, "SELECT COUNT(*) FROM saved_notes WHERE user_id = ?", (uid,)) == 0
    assert _count(db_path, "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (uid,)) == 0


def test_new_columns_have_defaults_on_fresh_rows(client: TestClient, db_path) -> None:
    kid = _register(client, "kid@example.com", "student")
    teach = _register(client, "teach@example.com", "teacher")
    uid = _user_id(db_path, "kid@example.com")
    tid = _user_id(db_path, "teach@example.com")
    conn = sqlite3.connect(db_path)
    try:
        student = conn.execute(
            "SELECT learning_prefs, memory_enabled FROM students WHERE user_id = ?", (uid,)
        ).fetchone()
        teacher = conn.execute("SELECT prefs FROM teachers WHERE user_id = ?", (tid,)).fetchone()
    finally:
        conn.close()
    assert student[0] is None or student[0] == "{}"
    assert int(student[1]) == 1, "memory_enabled defaults to true"
    assert teacher[0] is None or teacher[0] == "{}"
    assert "Authorization" in kid and "Authorization" in teach
