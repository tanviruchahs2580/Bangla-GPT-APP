"""H-08 / AUD-HI-08: failure injection between the steps of multi-step writes.

The audit found strong declarative integrity but no evidence of what happens
when a process dies *between* the steps of a write that touches several rows
or tables. Each test below injects a failure at the exact point a crash would
land and asserts the primary state from a second connection -- so a stray
intermediate commit would be visible and would fail the test.

Covered paths:

* classroom CSV import (user + student + enrollment + invite in one request);
* quiz grading (the atomic open->graded claim plus the answer rows);
* the retention sweep (six deletes that must be one transaction).

What the tests deliberately do NOT claim: the *after-commit* enrichment that
follows grading (activity, revision queue, mastery) runs in its own
transactions in ``routers/learn.py``; a crash there loses the enrichment but
never corrupts or half-writes the graded attempt. That boundary is documented
in the finding's note with the router owner as the follow-up.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services import retention

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
# "রহিম" (NFC: ya+nukta is U+09AF U+09BC).
RAHIM = "\u09b0\u09b9\u09bf\u09ae"


def _settings(db_path: Path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{db_path}",
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
        chat_retention_days=30,
    )


def _counts(db_path: Path, *queries: str) -> tuple[int, ...]:
    """Counts read through a SEPARATE connection (no uncommitted view)."""
    return tuple(int(value) for value in _scalars(db_path, *queries))


def _scalars(db_path: Path, *queries: str) -> tuple[object, ...]:
    """Raw first-column values through a separate connection."""
    conn = sqlite3.connect(db_path)
    try:
        return tuple(conn.execute(query).fetchone()[0] for query in queries)
    finally:
        conn.close()


# ── 1. CSV import: one transaction, all four rows or none ──────────────


def test_csv_import_is_all_or_nothing_when_a_step_fails(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "import.db"
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    from bangla_gpt_api.main import create_app as build

    client = TestClient(build(_settings(db_path)), raise_server_exceptions=False)
    registration = client.post(
        "/auth/register",
        json={"email": "t@example.com", "password": PASSWORD, "name": "Tania", "role": "teacher"},
    )
    assert registration.status_code == 201, registration.text
    login = client.post("/auth/login", json={"email": "t@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    room = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": "FI"}, headers=headers
    ).json()["id"]

    # Crash on the THIRD invite code: two students are already flushed, so a
    # missing transaction boundary would leave them behind.
    import bangla_gpt_api.routers.teacher as teacher_module

    real_token = teacher_module.secrets.token_urlsafe
    calls = {"n": 0}

    def failing_token(nbytes: int = 32, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("injected crash after two students were prepared")
        return real_token(nbytes, *args, **kwargs)

    monkeypatch.setattr(teacher_module.secrets, "token_urlsafe", failing_token)
    rows = "\n".join(f"{RAHIM} {i},fi-{i}@example.com" for i in range(1, 5))
    response = client.post(
        f"/teacher/classrooms/{room}/import",
        json={"csv_text": f"name,email\n{rows}"},
        headers=headers,
    )
    assert response.status_code == 500, response.text
    monkeypatch.undo()

    users, students, links, invites = _counts(
        db_path,
        "SELECT count(*) FROM users WHERE email LIKE 'fi-%'",
        f"SELECT count(*) FROM students WHERE name LIKE '{RAHIM}%'",
        "SELECT count(*) FROM class_students",
        "SELECT count(*) FROM student_invites",
    )
    assert (users, students, links, invites) == (0, 0, 0, 0)

    # The same request without the injected failure still works end to end.
    ok = client.post(
        f"/teacher/classrooms/{room}/import",
        json={"csv_text": f"name,email\n{rows}"},
        headers=headers,
    )
    assert ok.status_code == 200 and ok.json()["created"] == 4, ok.text


# ── 2. quiz grading: the claim and the answers share one transaction ───


def test_quiz_grading_rolls_back_the_claim_when_an_answer_row_fails(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "quiz.db"
    settings = _settings(db_path)
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    registered = client.post(
        "/auth/register",
        json={
            "email": "s@example.com",
            "password": PASSWORD,
            "name": "Sadia",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert registered.status_code == 201, registered.text
    login = client.post("/auth/login", json={"email": "s@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    conn = sqlite3.connect(db_path)
    try:
        student_id = conn.execute(
            "SELECT s.id FROM students s JOIN users u ON s.user_id=u.id WHERE u.email='s@example.com'"
        ).fetchone()[0]
        now = str(datetime.now(UTC).replace(tzinfo=None))
        # Real quiz_json rows carry a stable question id (adaptive.apply_review
        # keys the Elo update on it), so the fixture must too.
        quiz_json = (
            '[{"id": "q1", "question_text": "q1", "options": ["a", "b"], "answer_index": 0,'
            ' "chapter": "c", "book": "b"},'
            ' {"id": "q2", "question_text": "q2", "options": ["a", "b"], "answer_index": 1,'
            ' "chapter": "c", "book": "b"}]'
        )
        conn.execute(
            "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total, correct,"
            " score_pct, quiz_json, created_at) VALUES (?, 'math', 6, 'open', NULL, NULL, NULL, ?, ?)",
            (student_id, quiz_json, now),
        )
        attempt_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    import bangla_gpt_api.routers.learn as learn_module

    class ExplodingAnswerLog(learn_module.AnswerLog):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs) -> None:
            if kwargs.get("seq") == 1:
                raise RuntimeError("injected crash on the second answer row")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(learn_module, "AnswerLog", ExplodingAnswerLog)
    response = client.post(
        f"/quizzes/{attempt_id}/submit", json={"answers": [0, 1]}, headers=headers
    )
    assert response.status_code == 500, response.text
    monkeypatch.undo()

    status, logs = _scalars(
        db_path,
        f"SELECT status FROM quiz_attempts WHERE id = {attempt_id}",
        f"SELECT count(*) FROM answer_log WHERE attempt_id = {attempt_id}",
    )
    # The claim ran before the injected failure, so a missing transaction
    # boundary would leave a graded attempt with no answers.
    assert str(status) == "open", status
    assert int(logs) == 0

    retry = client.post(f"/quizzes/{attempt_id}/submit", json={"answers": [0, 1]}, headers=headers)
    assert retry.status_code == 200, retry.text
    status, logs = _scalars(
        db_path,
        f"SELECT status FROM quiz_attempts WHERE id = {attempt_id}",
        f"SELECT count(*) FROM answer_log WHERE attempt_id = {attempt_id}",
    )
    assert str(status) == "graded" and int(logs) == 2


# ── 3. retention sweep: no partial delete is ever visible ─────────────


def test_retention_sweep_failure_leaves_every_row_in_place(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "sweep.db"
    settings = _settings(db_path)
    engine = make_engine(settings)
    init_db(engine)
    factory = make_session_factory(engine)
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=400)
    with factory() as db:
        from bangla_gpt_api.db.models import (
            ChatMessage,
            Conversation,
            EmailVerification,
            PasswordReset,
            Student,
            User,
        )

        user = User(email="sweep@example.com", password_hash="x", role="student")
        db.add(user)
        db.flush()
        student = Student(
            user_id=user.id, name=RAHIM, class_level=6, consent_version="T-1", consent_at=None
        )
        db.add(student)
        db.flush()
        conversation = Conversation(student_id=student.id, created_at=old)
        db.add(conversation)
        db.flush()
        db.add(
            ChatMessage(conversation_id=conversation.id, role="user", content="x", created_at=old)
        )
        db.add(PasswordReset(user_id=user.id, token_hash="e" * 64, expires_at=old))
        db.add(EmailVerification(user_id=user.id, token_hash="f" * 64, expires_at=old))
        db.commit()

        real_execute = db.execute
        original = real_execute

        def exploding_execute(statement, *args, **kwargs):  # noqa: ANN001
            if "DELETE FROM email_verifications" in str(statement):
                raise RuntimeError("injected crash between the sweep's steps")
            return original(statement, *args, **kwargs)

        monkeypatch.setattr(db, "execute", exploding_execute)
        with pytest.raises(RuntimeError, match="injected crash"):
            retention.run_retention_sweep(db, settings=settings)
        monkeypatch.undo()
        db.rollback()

    persisted = _counts(
        db_path,
        "SELECT count(*) FROM conversations",
        "SELECT count(*) FROM chat_messages",
        "SELECT count(*) FROM password_resets",
        "SELECT count(*) FROM email_verifications",
    )
    assert persisted == (1, 1, 1, 1), persisted

    # And the unbroken sweep does remove all four.
    with factory() as db:
        report = retention.run_retention_sweep(db, settings=settings)
        db.commit()
    assert report["conversations_deleted"] == 1
    assert report["chat_messages_deleted"] == 1
    assert report["password_resets_deleted"] == 1
    assert report["email_verifications_deleted"] == 1
    assert _counts(
        db_path,
        "SELECT count(*) FROM conversations",
        "SELECT count(*) FROM chat_messages",
        "SELECT count(*) FROM password_resets",
        "SELECT count(*) FROM email_verifications",
    ) == (0, 0, 0, 0)
