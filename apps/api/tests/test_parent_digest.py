"""S3.4 PASS-WHEN: weekly parent digest is summary-only; no raw messages leak."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.parent_digest import (
    ChildSummary,
    WeeklyDigest,
    build_body,
    digest_due,
    run_weekly_digest,
)

PASSWORD = "supersecret1"
SENTINEL = "SENTINEL-private-message-text-42"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _ts(dt: datetime) -> str:
    return str(dt)


# ---------- pure scheduler rule ----------


def test_digest_due_rule() -> None:
    sunday_1559 = datetime(2026, 9, 6, 15, 59)  # Sunday
    sunday_1600 = datetime(2026, 9, 6, 16, 0)
    monday = datetime(2026, 9, 7, 18, 0)
    assert digest_due(sunday_1559, "") == (False, "")
    due, key = digest_due(sunday_1600, "")
    assert due and key == "2026-W36"
    # already sent this ISO week -> deduped
    assert digest_due(sunday_1600, key) == (False, key)
    # not Sunday at all
    assert digest_due(monday, "") == (False, "")
    # a new ISO week fires again
    due2, key2 = digest_due(datetime(2026, 9, 13, 17, 0), key)
    assert due2 and key2 == "2026-W37"


# ---------- pure body builder ----------


def test_build_body_aggregates_only() -> None:
    digest = WeeklyDigest(
        parent_name="Ayesha",
        week_label="30 Aug – 06 Sep",
        children=[
            ChildSummary("Rahim", 6, 3, 2, 55.0, True, ["Algebra", "Geometry"]),
            ChildSummary("Karim", 7, 0, 0, None, False, []),
        ],
    )
    body = build_body(digest)
    assert "Ayesha" in body
    line = "Rahim (class 6): 3 study session(s), 2 graded attempt(s), average 55.0%"
    assert line + " -- needs support." in body
    assert "Chapters to practise: Algebra, Geometry" in body
    assert "No activity this week" in body
    assert "summary statistics only" in body


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/digest.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/digest.db")
    yield client, conn, settings
    conn.close()


def _seed_family(conn: sqlite3.Connection, parent_id: int) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO users (email, password_hash, role, created_at)"
        " VALUES ('kid@dig.test', 'x', 'student', ?)",
        (_ts(now),),
    )
    sid = conn.execute("SELECT id FROM users WHERE email='kid@dig.test'").fetchone()[0]
    conn.execute(
        "INSERT INTO students (user_id, name, class_level, consent_version, consent_at, created_at)"
        " VALUES (?, 'Rahim', 6, 'T-1', ?, ?)",
        (sid, _ts(now), _ts(now)),
    )
    student_id = conn.execute("SELECT id FROM students WHERE user_id=?", (sid,)).fetchone()[0]
    conn.execute(
        "INSERT INTO parent_student_links (parent_id, student_id, created_at) VALUES (?, ?, ?)",
        (parent_id, student_id, _ts(now)),
    )
    # 2 recent sessions + 1 with a private sentinel title and message
    for hours, title in ((1, "Algebra help"), (5, SENTINEL)):
        conn.execute(
            "INSERT INTO conversations (student_id, title, last_strategy, created_at)"
            " VALUES (?, ?, NULL, ?)",
            (student_id, title, _ts(now - timedelta(hours=hours))),
        )
    conv_id = conn.execute("SELECT id FROM conversations WHERE title=?", (SENTINEL,)).fetchone()[0]
    conn.execute(
        "INSERT INTO chat_messages (conversation_id, role, content, created_at)"
        " VALUES (?, 'user', ?, ?)",
        (conv_id, SENTINEL, _ts(now - timedelta(hours=5))),
    )
    # graded attempt inside the week: Algebra 1/3 (33%), Geometry 2/2 (100%)
    conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total, correct,"
        " score_pct, quiz_json, created_at) VALUES (?, 'math', 6, 'graded', 5, 3, 60.0, '[]', ?)",
        (student_id, _ts(now - timedelta(hours=2))),
    )
    att = conn.execute("SELECT id FROM quiz_attempts WHERE student_id=?", (student_id,)).fetchone()[
        0
    ]
    seq = 0
    for chapter, ok in (("Algebra", 0), ("Algebra", 0), ("Algebra", 1), ("Geometry", 1)):
        seq += 1
        conn.execute(
            "INSERT INTO answer_log (attempt_id, seq, question_text, chosen, correct_index,"
            " is_correct, chapter, book) VALUES (?, ?, 'q', 0, 0, ?, ?, 'b')",
            (att, seq, int(ok), chapter),
        )
    # old graded attempt OUTSIDE the week -- must not be counted
    conn.execute(
        "INSERT INTO quiz_attempts (student_id, subject, class_level, status, total, correct,"
        " score_pct, quiz_json, created_at) VALUES (?, 'math', 6, 'graded', 1, 1, 100.0, '[]', ?)",
        (student_id, _ts(now - timedelta(days=9))),
    )
    conn.commit()


def _register_parent(client: TestClient, conn: sqlite3.Connection, email: str, name: str) -> int:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "role": "parent", "name": name},
    )
    assert res.status_code == 201, res.text
    return int(
        conn.execute(
            "SELECT p.id FROM parents p JOIN users u ON p.user_id=u.id WHERE u.email=?", (email,)
        ).fetchone()[0]
    )


def test_digest_content_no_raw_messages(env) -> None:
    client, conn, settings = env
    parent_id = _register_parent(client, conn, "par@dig.test", "Ayesha")
    _seed_family(conn, parent_id)
    # second parent without any linked child must not receive a digest
    _register_parent(client, conn, "lonely@dig.test", "NoLink")

    sent: list[dict] = []

    def fake_sender(_settings: Settings, *, to: str, subject: str, body: str) -> bool:
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    session = make_session_factory(make_engine(settings))()
    try:
        stats = run_weekly_digest(settings, session, sender=fake_sender, now=_now())
    finally:
        session.close()
    assert stats.families == 1 and stats.delivered == 1 and stats.undelivered == 0
    assert stats.skipped is None
    assert len(sent) == 1 and sent[0]["to"] == "par@dig.test"
    assert "Weekly parent digest" in sent[0]["subject"]
    body = sent[0]["body"]
    # aggregates present, week-window enforced (the 9-day-old attempt excluded)
    line = "Rahim (class 6): 2 study session(s), 1 graded attempt(s), average 60.0%"
    assert line + " -- on track." in body
    assert "Chapters to practise: Algebra" in body
    # R11 hard rule: no message/title content, ever
    assert SENTINEL not in body and SENTINEL not in sent[0]["subject"]
    assert "Algebra help" not in body


def test_digest_skips_without_smtp(env) -> None:
    client, conn, settings = env
    parent_id = _register_parent(client, conn, "par2@dig.test", "Nasrin")
    _seed_family(conn, parent_id)
    session = make_session_factory(make_engine(settings))()
    try:
        stats = run_weekly_digest(settings, session, now=_now())
    finally:
        session.close()
    assert stats.skipped == "smtp_not_configured" and stats.delivered == 0


def test_scheduler_starts_and_stops_with_app(tmp_path) -> None:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/sched.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        task = client.app.state.digest_task
        assert task is not None and not task.done()
    # shutdown cancelled the loop
    assert task.cancelled() or task.done()
