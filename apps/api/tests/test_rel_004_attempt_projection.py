"""REL-004: the per-visit attempt reads stop loading the quiz payload.

The student dashboard (`/dashboard/summary`, loaded on every visit) and the
guardian progress view selected whole ``QuizAttempt`` rows and filtered in
Python, while each row carries the full question set in ``quiz_json`` on a
table with no retention window. Both now select only the columns the
aggregate uses; the dashboard defers ``quiz_json`` and lazy-loads it for the
couple of rows its continue/recommendation outputs inspect.

These tests seed known attempts and answer rows over raw SQLite and assert the
endpoint's numbers are EXACTLY the values the old query produced, plus the
projection property itself (the student-id load carries no ``quiz_json``; the
guardian view never mentions it at all).

Engine-coupled by design (raw sqlite3 seeding, like tests/test_scale_v2.py),
so this file stays SQLite and out of the BGPT_TEST_DATABASE_URL parity lane.
New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import bangla_gpt_api.main as bgpt_main
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
# "durbol odhyay" -- the recommendation reason the weak-chapter branch mints
WEAK_REASON = "\u09a6\u09c1\u09b0\u09cd\u09ac\u09b2 \u0985\u09a7\u09cd\u09af\u09be\u09af\u09bc"
LONG_QUESTION = "Q" * 200


@pytest.fixture
def env(tmp_path, monkeypatch):
    """App client + raw connection + every SQL statement the app executes."""
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/rel004.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    statements: list[str] = []
    real = bgpt_main.make_engine

    def wrapping_make_engine(cfg: Settings):
        engine = real(cfg)
        event.listen(
            engine,
            "before_cursor_execute",
            lambda conn, cursor, statement, params, ctx, executemany: statements.append(statement),
        )
        return engine

    monkeypatch.setattr(bgpt_main, "make_engine", wrapping_make_engine)
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/rel004.db")
    yield client, conn, statements
    conn.close()


def _register(client: TestClient, role: str, email: str, **extra) -> dict:
    payload = {"email": email, "password": PASSWORD, "role": role, "name": "Tester"}
    payload.update(extra)
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _student_id(conn, email: str) -> int:
    row = conn.execute(
        "SELECT s.id FROM students s JOIN users u ON u.id = s.user_id WHERE u.email = ?",
        (email,),
    ).fetchone()
    assert row is not None, f"no student row for {email}"
    return int(row[0])


def _seed_attempt(
    conn,
    student_id: int,
    *,
    score: float | None,
    when: datetime,
    subject: str,
    chapter: str,
    question: str,
    status: str = "graded",
) -> int:
    conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total, correct,"
        " score_pct, quiz_json, created_at) VALUES (?, ?, 6, ?, 10, 8, ?, ?, ?)",
        (
            student_id,
            subject,
            status,
            score,
            json.dumps([{"chapter": chapter, "question_text": question}]),
            when.isoformat(sep=" "),
        ),
    )
    conn.commit()
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _seed_answers(conn, attempt_id: int, chapter: str, *, correct: int, asked: int) -> None:
    conn.executemany(
        "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
        " is_correct, chapter, book) VALUES (?, ?, 'Q', 0, 0, ?, ?, 'book')",
        [(attempt_id, i, int(i < correct), chapter) for i in range(asked)],
    )
    conn.commit()


def _seed_student_history(conn, student_id: int, base: datetime) -> None:
    """Three graded attempts (scores 40/80/100) + one open attempt.

    Answer evidence: algebra 1/4 (weak), cell 4/4, cell3 2/2 -- so the weak
    chapter is algebra while the newest attempt's chapter is cell3.
    """
    a1 = _seed_attempt(
        conn,
        student_id,
        score=40.0,
        when=base,
        subject="math",
        chapter="algebra",
        question="first question",
    )
    a2 = _seed_attempt(
        conn,
        student_id,
        score=80.0,
        when=base + timedelta(hours=1),
        subject="science",
        chapter="cell",
        question="second question",
    )
    a3 = _seed_attempt(
        conn,
        student_id,
        score=100.0,
        when=base + timedelta(hours=2),
        subject="science",
        chapter="cell3",
        question=LONG_QUESTION,
    )
    _seed_attempt(
        conn,
        student_id,
        score=None,
        when=base + timedelta(hours=3),
        subject="science",
        chapter="cell4",
        question="ungraded",
        status="open",
    )
    _seed_answers(conn, a1, "algebra", correct=1, asked=4)
    _seed_answers(conn, a2, "cell", correct=4, asked=4)
    _seed_answers(conn, a3, "cell3", correct=2, asked=2)


def test_dashboard_summary_numbers_unchanged_and_payload_not_loaded(env) -> None:
    client, conn, statements = env
    headers = _register(
        client, "student", "rel004-student@example.test", guardian_consent=True, class_level=6
    )
    sid = _student_id(conn, "rel004-student@example.test")
    base = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
    _seed_student_history(conn, sid, base)

    mark = len(statements)
    res = client.get("/dashboard/summary", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    window = statements[mark:]

    # exact aggregates: what the old whole-row load produced
    progress = body["progress"]
    assert progress["attempts_graded"] == 3, "the open attempt must not count"
    assert progress["avg_score_pct"] == round((40.0 + 80.0 + 100.0) / 3, 2)
    assert progress["by_chapter"] == [
        {"chapter": "algebra", "asked": 4, "correct": 1, "accuracy": 25.0},
        {"chapter": "cell", "asked": 4, "correct": 4, "accuracy": 100.0},
        {"chapter": "cell3", "asked": 2, "correct": 2, "accuracy": 100.0},
    ]
    assert progress["weak_chapters"] == ["algebra"]
    # the two payload-consuming outputs are unchanged too
    assert body["continue_learning"] == {
        "subject": "science",
        "chapter": "cell3",
        "class_level": 6,
        "excerpt": LONG_QUESTION[:120],
    }
    assert body["recommendation"] == {
        "type": "weak_quiz",
        "subject": "math",
        "chapter": "algebra",
        "reason": WEAK_REASON,
    }

    # projection: the roster load carries no quiz_json; the payload is read
    # only for the rows the two outputs above actually inspect
    loads = [s for s in window if "FROM quiz_attempts" in s and "student_id = ?" in s]
    assert loads, window
    assert all("quiz_json" not in s for s in loads), loads
    payload_loads = [s for s in window if "FROM quiz_attempts" in s and "quiz_json" in s]
    assert len(payload_loads) <= 2, payload_loads


def test_guardian_progress_numbers_unchanged_and_payload_not_loaded(env) -> None:
    client, conn, statements = env
    child = _register(
        client, "student", "rel004-child@example.test", guardian_consent=True, class_level=6
    )
    assert child  # the child's session is not needed; registration creates the row
    guardian = _register(client, "parent", "rel004-parent@example.test")
    sid = _student_id(conn, "rel004-child@example.test")
    parent_profile = client.get("/users/me", headers=guardian).json()["profile_id"]
    conn.execute(
        "INSERT INTO parent_student_links (parent_id, student_id, created_at) VALUES (?, ?, ?)",
        (parent_profile, sid, datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")),
    )
    conn.commit()
    base = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
    _seed_student_history(conn, sid, base)

    mark = len(statements)
    res = client.get(f"/parents/me/children/{sid}/progress", headers=guardian)
    assert res.status_code == 200, res.text
    body = res.json()
    window = statements[mark:]

    assert body["student"] == {"id": sid, "name": "Tester", "class_level": 6}
    assert body["attempts_graded"] == 3
    assert body["avg_score_pct"] == round((40.0 + 80.0 + 100.0) / 3, 2)
    assert body["by_chapter"] == [
        {"chapter": "algebra", "asked": 4, "correct": 1, "accuracy": 25.0},
        {"chapter": "cell", "asked": 4, "correct": 4, "accuracy": 100.0},
        {"chapter": "cell3", "asked": 2, "correct": 2, "accuracy": 100.0},
    ]
    assert body["weak_chapters"] == ["algebra"]

    # this view reads no question set at all
    assert any("FROM quiz_attempts" in s for s in window), window
    assert all("quiz_json" not in s for s in window), window


def test_guardian_progress_refuses_a_child_without_a_link(env) -> None:
    """Negative case: no link means the same 404, never another child's data.

    The projection change must not have widened the access check: an
    unlinked student id, and a guardian account whose profile row is absent,
    are both answered `not_linked`.
    """
    client, conn, _statements = env
    child = _register(
        client, "student", "rel004-child2@example.test", guardian_consent=True, class_level=6
    )
    assert child
    guardian = _register(client, "parent", "rel004-guardian2@example.test")
    sid = _student_id(conn, "rel004-child2@example.test")

    unlinked = client.get(f"/parents/me/children/{sid}/progress", headers=guardian)
    assert unlinked.status_code == 404
    assert unlinked.json()["detail"]["code"] == "not_linked"

    # a guardian account whose profile row is gone must not 500 either
    profile_id = client.get("/users/me", headers=guardian).json()["profile_id"]
    conn.execute("DELETE FROM parents WHERE id = ?", (profile_id,))
    conn.commit()
    no_profile = client.get(f"/parents/me/children/{sid}/progress", headers=guardian)
    assert no_profile.status_code == 404
    assert no_profile.json()["detail"]["code"] == "not_linked"
