"""REL-003: analytics id lists are batched, and the results do not change.

`/teacher/classes/{level}/analytics` bound every student id of a class into
one ``IN (...)`` and then every attempt id into a second one;
`/school/classes` did the same for a whole school through the shared
percents helper plus an inline count. Past the engine's bind limit (~32k on
SQLite, 65535 on PostgreSQL) those endpoints answered 500; the codebase
already batches at 500 in ``_student_briefs``.

These tests seed >500 students and assert BOTH halves of the fix:
batching really happens (no statement carries more than 500 binds) and the
numbers are exactly the values an unbounded query would have produced --
computed here independently for a 501-student and a 2-student class, so the
assertion is scale-invariance, not merely "no exception was raised".

Engine-coupled by design (raw sqlite3 seeding, like tests/test_scale_v2.py),
so this file stays SQLite and out of the BGPT_TEST_DATABASE_URL parity lane.
New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import bangla_gpt_api.main as bgpt_main
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
BIG_CLASS = 501  # > _ID_CHUNK_SIZE, so the batched paths must split
SCORES = (60.0, 80.0, 100.0)  # mean over 501 students is exactly 80.0
ANALYTICS_URL = "/teacher/classes/6/analytics"


def _settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/rel003.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="rel003-root@example.test",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    """App client + raw connection + every SQL statement the app executes."""
    settings = _settings(tmp_path)
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
    conn = sqlite3.connect(f"{tmp_path}/rel003.db")
    yield client, conn, statements
    conn.close()


def _ts(dt: datetime) -> str:
    return dt.isoformat(sep=" ")


def _login(client: TestClient, email: str) -> dict:
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _register(client: TestClient, role: str, email: str) -> dict:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "role": role, "name": "Tester"},
    )
    assert res.status_code == 201, res.text
    return _login(client, email)


def _seed_students(conn, prefix: str, count: int, class_level: int) -> list[int]:
    """Count students (users + profiles) and return their ids in order."""
    now = _ts(datetime.now(UTC).replace(tzinfo=None))
    emails = [f"{prefix}{i:04d}@example.test" for i in range(count)]
    conn.executemany(
        "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, 'x', 'student', ?)",
        [(email, now) for email in emails],
    )
    conn.executemany(
        "INSERT INTO students (user_id, name, class_level, consent_version, consent_at, created_at)"
        " VALUES ((SELECT id FROM users WHERE email=?), ?, ?, 'T-1', ?, ?)",
        [(email, f"Pupil {i}", class_level, now, now) for i, email in enumerate(emails)],
    )
    conn.commit()
    rows = conn.execute(
        "SELECT id FROM students WHERE user_id IN (SELECT id FROM users WHERE email LIKE ?)"
        " ORDER BY id",
        (f"{prefix}%",),
    ).fetchall()
    assert len(rows) == count
    return [int(r[0]) for r in rows]


def _seed_attempts(conn, student_ids: list[int], scores: tuple[float, ...]) -> None:
    """One graded attempt per student, score cycling through ``scores``."""
    now = _ts(datetime.now(UTC).replace(tzinfo=None))
    conn.executemany(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total, correct,"
        " score_pct, quiz_json, created_at) VALUES (?, 'math', 6, 'graded', 10, 8, ?, '[]', ?)",
        [(sid, scores[i % len(scores)], now) for i, sid in enumerate(student_ids)],
    )
    conn.commit()


def _seed_answers(conn, attempt_id: int, chapter: str, correct: int, asked: int) -> None:
    conn.executemany(
        "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
        " is_correct, chapter, book) VALUES (?, ?, 'Q', 0, 0, ?, ?, 'book')",
        [(attempt_id, i, int(i < correct), chapter) for i in range(asked)],
    )
    conn.commit()


def _attempt_id(conn, student_id: int) -> int:
    return int(
        conn.execute("SELECT id FROM quiz_attempts WHERE student_id=?", (student_id,)).fetchone()[0]
    )


def _max_in_binds(statements: list[str]) -> int:
    """Largest ``IN (...)`` bind list in the executed statements."""
    largest = 0
    for statement in statements:
        for match in re.finditer(r"IN\s*\(([^)]*)\)", statement, re.IGNORECASE):
            largest = max(largest, match.group(1).count("?"))
    return largest


def test_class_analytics_batches_and_matches_the_unbatched_numbers(env) -> None:
    client, conn, statements = env
    teacher = _register(client, "teacher", "rel003-teacher@example.test")
    room = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "A"}, headers=teacher
    )
    assert room.status_code == 201, room.text
    room_id = room.json()["id"]

    big = _seed_students(conn, "rel003big", BIG_CLASS, 6)
    small = _seed_students(conn, "rel003small", 2, 7)
    second_room = client.post(
        "/teacher/classrooms", json={"class_level": 7, "section": "A"}, headers=teacher
    )
    assert second_room.status_code == 201, second_room.text
    conn.executemany(
        "INSERT INTO class_students (classroom_id, student_id, created_at) VALUES (?, ?, ?)",
        [(room_id, sid, _ts(datetime.now(UTC).replace(tzinfo=None))) for sid in big]
        + [
            (second_room.json()["id"], sid, _ts(datetime.now(UTC).replace(tzinfo=None)))
            for sid in small
        ],
    )
    conn.commit()
    _seed_attempts(conn, big, SCORES)
    _seed_attempts(conn, small, SCORES[:2])
    # answer evidence for the first and the last student of the big class, so
    # the attempt-id IN list must also be built from the batched id list
    _seed_answers(conn, _attempt_id(conn, big[0]), "cell", correct=3, asked=4)
    _seed_answers(conn, _attempt_id(conn, big[-1]), "algebra", correct=1, asked=4)

    mark = len(statements)
    res = client.get(ANALYTICS_URL, headers=teacher)
    assert res.status_code == 200, res.text
    window = statements[mark:]
    body = res.json()

    # equivalence: exactly what the per-student aggregates must be
    assert body["class_level"] == 6
    assert body["students"] == BIG_CLASS
    assert len(body["students_detail"]) == BIG_CLASS
    assert {b["attempts_graded"] for b in body["students_detail"]} == {1}
    assert sorted({b["avg_score_pct"] for b in body["students_detail"]}) == sorted(SCORES)
    assert {b["class_level"] for b in body["students_detail"]} == {6}
    assert body["chapters"] == [
        {"chapter": "algebra", "asked": 4, "correct": 1, "accuracy": 25.0},
        {"chapter": "cell", "asked": 4, "correct": 3, "accuracy": 75.0},
    ]
    assert body["weak_chapters"] == ["algebra"]

    # batching: no statement binds more than the shared chunk size
    assert window, "expected the endpoint to query the database"
    assert _max_in_binds(window) <= 500, _max_in_binds(window)
    # the class-wide attempt read really was split (501 ids -> 2 statements)
    attempt_reads = [s for s in window if "FROM quiz_attempts" in s and "student_id IN" in s]
    assert len(attempt_reads) >= 2, window

    # scale invariance: the same scores on a 2-student class give the same
    # per-student numbers (only the roster size differs)
    small_body = client.get("/teacher/classes/7/analytics", headers=teacher).json()
    assert small_body["students"] == 2
    assert len(small_body["students_detail"]) == 2
    assert {b["attempts_graded"] for b in small_body["students_detail"]} == {1}
    assert sorted({b["avg_score_pct"] for b in small_body["students_detail"]}) == sorted(SCORES[:2])
    assert small_body["chapters"] == []


def test_school_classes_batches_and_matches_the_unbatched_numbers(env) -> None:
    client, conn, statements = env
    # the platform admin is seeded by create_app (admin_email/admin_password)
    admin = _login(client, "rel003-root@example.test")
    now = _ts(datetime.now(UTC).replace(tzinfo=None))
    conn.execute(
        "INSERT INTO schools (name, code, created_at) VALUES ('Rel003 School', 'REL003', ?)",
        (now,),
    )
    school_id = int(conn.execute("SELECT id FROM schools WHERE code='REL003'").fetchone()[0])
    conn.execute(
        "INSERT INTO classrooms (school_id, class_level, section, created_at)"
        " VALUES (?, 6, 'A', ?)",
        (school_id, now),
    )
    room_id = int(
        conn.execute(
            "SELECT id FROM classrooms WHERE school_id=? AND class_level=6", (school_id,)
        ).fetchone()[0]
    )
    students = _seed_students(conn, "rel003school", BIG_CLASS, 6)
    conn.executemany(
        "INSERT INTO class_students (classroom_id, student_id, created_at) VALUES (?, ?, ?)",
        [(room_id, sid, now) for sid in students],
    )
    conn.commit()
    _seed_attempts(conn, students, SCORES)
    _seed_answers(conn, _attempt_id(conn, students[0]), "cell", correct=3, asked=4)

    mark = len(statements)
    res = client.get(f"/school/classes?school_id={school_id}", headers=admin)
    assert res.status_code == 200, res.text
    window = statements[mark:]
    rows = res.json()
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["classroom_id"] == room_id
    assert row["students"] == BIG_CLASS
    assert row["quiz_attempts"] == BIG_CLASS
    assert row["attempts_graded"] == BIG_CLASS
    assert row["avg_quiz_accuracy"] == 80.0

    assert window, "expected the endpoint to query the database"
    assert _max_in_binds(window) <= 500, _max_in_binds(window)
