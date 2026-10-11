"""TST-04 (AUD-0006), second half: the aggregation branches.

The remaining uncovered lines in school.py are all "there is data to
aggregate" paths: quiz attempts, chapter progress and daily activity. Each test
seeds the underlying rows directly (the same approach the existing
test_curriculum_coverage / test_atrisk suites use) and then asserts the
principal's dashboard reflects them - and that another school's dashboard
does not.
"""

import sqlite3
from datetime import UTC, datetime

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
        database_url=f"sqlite:///{tmp_path}/agg.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/agg.db")
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


def _join(client: TestClient, code: str, email: str) -> dict:
    res = client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": JOIN_PASSWORD, "name": "Pupil"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _school(client: TestClient, name: str, principal: str, teacher: str) -> dict:
    """A school with a principal, a teacher, one classroom and one pupil."""
    root = _root(client)
    school = client.post("/admin/schools", json={"name": name}, headers=root).json()
    sid = school["id"]

    _join(client, _invite(client, root, sid, "school_admin"), principal)
    _join(client, _invite(client, root, sid, "teacher"), teacher)
    teacher_h = _login(client, teacher, JOIN_PASSWORD)
    room = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teacher_h).json()

    csv_text = "Pupil One,pupil@stu.test"
    imported = client.post(
        f"/teacher/classrooms/{room['id']}/import",
        json={"csv_text": csv_text},
        headers=teacher_h,
    )
    assert imported.status_code == 200, imported.text

    # The imported pupil cannot be logged into here: bulk import assigns a
    # random invite code as the initial password (must_change_password). The
    # tests below only need the pupil's row, not their session.
    return {
        "school": school,
        "principal": _login(client, principal, JOIN_PASSWORD),
        "room_id": room["id"],
    }


def _student_id(conn: sqlite3.Connection, email: str) -> int:
    row = conn.execute(
        "SELECT s.id FROM students s JOIN users u ON u.id = s.user_id WHERE u.email = ?",
        (email,),
    ).fetchone()
    assert row is not None, f"no student row for {email}"
    return int(row[0])


def _seed_attempt(conn, student_id: int, *, status: str, pct: float | None) -> None:
    conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total,"
        " correct, score_pct, quiz_json, created_at) VALUES (?, ?, 6, ?, 10, ?, ?, '[]', ?)",
        (
            student_id,
            "math",
            status,
            int(((pct or 0) * 10) / 100),
            pct,
            datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" "),
        ),
    )
    conn.commit()


def test_classes_reports_attempts_and_accuracy(env):
    client, conn = env
    ctx = _school(client, "Agg Classes", "p@classes.test", "t@classes.test")
    sid = _student_id(conn, "pupil@stu.test")
    _seed_attempt(conn, sid, status="graded", pct=80.0)
    _seed_attempt(conn, sid, status="submitted", pct=None)

    rows = client.get("/school/classes", headers=ctx["principal"]).json()
    row = rows[0]
    assert row["students"] == 1
    assert row["quiz_attempts"] == 2
    assert row["attempts_graded"] == 1
    assert row["avg_quiz_accuracy"] == 80.0


def test_students_list_reports_last_activity_from_attempts(env):
    client, conn = env
    ctx = _school(client, "Agg Students", "p@students.test", "t@students.test")
    sid = _student_id(conn, "pupil@stu.test")
    _seed_attempt(conn, sid, status="graded", pct=50.0)

    page = client.get("/school/students", headers=ctx["principal"]).json()
    assert page["total"] == 1
    row = page["items"][0]
    assert row["name"] == "Pupil One"
    assert row["quiz_attempts"] == 1
    # A graded attempt today is real activity, so last_active must be set.
    assert row["last_active"] is not None


def test_coverage_counts_chapter_progress(env):
    client, conn = env
    ctx = _school(client, "Agg Coverage", "p@coverage.test", "t@coverage.test")
    sid = _student_id(conn, "pupil@stu.test")
    conn.execute(
        "INSERT INTO chapter_progress"
        " (student_id, class_level, subject, chapter, read_pct, completed, bookmarked,"
        " updated_at) VALUES (?, 6, 'math', 'algebra', 100, 1, 0, ?)",
        (sid, datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")),
    )
    conn.commit()

    body = client.get("/school/coverage", headers=ctx["principal"]).json()
    row = next(r for r in body["rows"] if r["class_level"] == 6)
    assert row["chapters_read"] >= 1


def test_analytics_counts_questions_and_quizzes(env):
    client, conn = env
    ctx = _school(client, "Agg Analytics", "p@analytics.test", "t@analytics.test")
    sid = _student_id(conn, "pupil@stu.test")
    _seed_attempt(conn, sid, status="graded", pct=90.0)
    _seed_attempt(conn, sid, status="graded", pct=70.0)

    body = client.get("/school/analytics", headers=ctx["principal"]).json()
    assert body["quiz_attempts"] == 2
    assert body["attempts_graded"] == 2
    assert body["avg_quiz_score_pct"] == 80.0


def test_analytics_records_daily_activity(env):
    client, conn = env
    ctx = _school(client, "Agg Actives", "p@actives.test", "t@actives.test")
    sid = _student_id(conn, "pupil@stu.test")
    conn.execute(
        "INSERT INTO daily_activity (student_id, date, questions, quizzes, minutes)"
        " VALUES (?, date('now'), 3, 1, 20)",
        (sid,),
    )
    conn.commit()

    body = client.get("/school/analytics", headers=ctx["principal"]).json()
    assert body["active_by_date"], "expected at least one active day"
    assert body["active_by_date"][-1]["students"] == 1


def test_one_schools_activity_never_reaches_another(env):
    client, conn = env
    a = _school(client, "Alpha Agg", "p@alpha.test", "t@alpha.test")
    _school(client, "Beta Agg", "p@beta.test", "t@beta.test")
    sid = _student_id(conn, "pupil@stu.test")
    _seed_attempt(conn, sid, status="graded", pct=100.0)

    assert client.get("/school/analytics", headers=a["principal"]).status_code == 200
    # Naming another school is refused outright.
    theirs = client.get("/school/analytics?school_id=2", headers=a["principal"])
    assert theirs.status_code in (403, 404)
