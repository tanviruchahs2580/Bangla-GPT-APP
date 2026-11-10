"""DAT-001/DAT-002: the chat sweep ages every row by its OWN timestamp.

The sweep used to age a conversation by ``Conversation.created_at`` (set once
at creation and never refreshed) and then delete every ``ChatMessage`` of that
conversation without a timestamp filter of its own -- while the web client
reuses ONE conversation per student until "New chat". With the shipped 180-day
window, the first sweep after a thread turned 180 days old deleted messages the
student had sent that same day: a year of tutoring history in one night, and
the report called it normal aging.

The invariant these tests pin (both halves):

* no row is deleted whose own timestamp is inside the window -- a
  ``chat_messages.created_at`` inside the window survives however old its
  conversation is;
* no orphan conversation is left behind -- a conversation the sweep has aged
  out of messages (or that holds nothing but expired messages) is removed, and
  a conversation that still holds a live message is kept.

DAT-002: the sweep must not wedge on the SQL bind-variable ceiling. SQLite caps
at 32766 variables (65535 on Postgres), and the pre-fix shape loaded every
expired conversation id into one Python list and re-bound the whole list on
every chunk, so above the ceiling the first chunk raised and -- the retry being
identical -- the sweep never drained. These tests run the sweep with the SQLite
limit LOWERED to one chunk (via ``sqlite3.Connection.setlimit``) over more rows
than that, and record the bind count of every statement.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, func, insert, select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    Base,
    ChatMessage,
    Conversation,
    Feedback,
    Student,
    User,
)
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.services.retention import DELETE_CHUNK, run_retention_sweep

# Fixed clock: the sweep takes ``now`` so the tests never race the wall clock.
NOW = datetime(2026, 11, 10, 3, 0, 0)
WINDOW_DAYS = 180
SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, name: str = "dat001", **over) -> Settings:
    """SQLite URL pinned by hand: these are engine-level tests (the SQLite
    variable ceiling, per-connection ``setlimit``), so the parity job must not
    redirect them to the shared Postgres database."""
    base = dict(
        env="test",
        database_url=f"sqlite:///{tmp_path}/{name}.db",
        jwt_secret=SECRET,
        chat_retention_days=WINDOW_DAYS,
        answer_log_retention_days=730,
        ai_usage_retention_days=365,
        ai_jobs_retention_days=30,
        analytics_retention_days=WINDOW_DAYS,
    )
    base.update(over)
    return Settings(**base)


@pytest.fixture
def sweep_env(tmp_path):
    """Settings + one open session over an isolated SQLite file database."""
    settings = _settings(tmp_path)
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    try:
        yield settings, session
    finally:
        session.close()


def _seed_student(db) -> Student:
    user = User(email="kid@example.test", password_hash="x", role="student", email_verified=True)
    db.add(user)
    db.flush()
    student = Student(name="Kid", class_level=6, user_id=user.id)
    db.add(student)
    db.flush()
    return student


def _seed_conversation(
    db,
    student: Student,
    *,
    created_days_ago: float,
    messages: list[tuple[str, str, float]],
) -> int:
    """A conversation created ``created_days_ago`` ago, holding ``messages``.

    Each message is ``(role, content, age_in_days)``: message age is what the
    retention window is really about, and it is deliberately independent of the
    conversation's own age so a 400-day-old thread can hold today's question.
    """
    conv = Conversation(
        student_id=student.id, title="t", created_at=NOW - timedelta(days=created_days_ago)
    )
    db.add(conv)
    db.flush()
    for role, content, age_days in messages:
        db.add(
            ChatMessage(
                conversation_id=conv.id,
                role=role,
                content=content,
                created_at=NOW - timedelta(days=age_days),
            )
        )
    db.commit()
    return conv.id


def _message_ids(db) -> list[int]:
    return list(db.execute(select(ChatMessage.id).order_by(ChatMessage.id)).scalars())


# --- the invariant: rows age on their own timestamp -------------------------


def test_a_message_sent_today_survives_the_sweep_of_its_400_day_old_thread(
    sweep_env,
) -> None:
    """The DAT-001 reproduction: one reused thread, one current question.

    Pre-fix, the conversation's 400-day-old ``created_at`` aged the message
    sent today and the sweep deleted it. Post-fix nothing is deleted here.
    """
    settings, db = sweep_env
    student = _seed_student(db)
    conv_id = _seed_conversation(
        db, student, created_days_ago=400, messages=[("user", "today's question", 0.5)]
    )

    report = run_retention_sweep(db, settings=settings, now=NOW)

    assert report["chat_messages_deleted"] == 0, "a message inside the window was deleted"
    assert report["conversations_deleted"] == 0, "its conversation still holds a live message"
    assert db.get(Conversation, conv_id) is not None
    rows = list(db.execute(select(ChatMessage.content)).scalars())
    assert rows == ["today's question"]


def test_only_the_expired_message_of_a_mixed_thread_is_deleted(sweep_env) -> None:
    """Old and recent turns in the same 400-day-old thread: only the old ones go."""
    settings, db = sweep_env
    student = _seed_student(db)
    conv_id = _seed_conversation(
        db,
        student,
        created_days_ago=400,
        messages=[
            ("user", "old question", 400),
            ("assistant", "old answer", 399),
            ("user", "recent question", 2),
        ],
    )

    dry = run_retention_sweep(db, settings=settings, dry_run=True, now=NOW)
    assert dry["dry_run"] is True
    assert dry["chat_messages_deleted"] == 2
    assert dry["conversations_deleted"] == 0, (
        "the thread is not empty; it must not be reported gone"
    )
    assert len(_message_ids(db)) == 3, "the dry run must not delete anything"

    report = run_retention_sweep(db, settings=settings, now=NOW)

    assert report["chat_messages_deleted"] == 2, "the report must match the rows the sweep removes"
    assert report["conversations_deleted"] == 0
    assert db.get(Conversation, conv_id) is not None
    survivors = list(db.execute(select(ChatMessage.content)).scalars())
    assert survivors == ["recent question"], "the in-window turn must survive the sweep"


def test_a_thread_left_empty_by_the_sweep_is_removed_not_orphaned(sweep_env) -> None:
    """The other half of the invariant: no orphan conversation row survives."""
    settings, db = sweep_env
    student = _seed_student(db)
    conv_id = _seed_conversation(
        db,
        student,
        created_days_ago=400,
        messages=[("user", "old question", 400), ("assistant", "old answer", 300)],
    )

    report = run_retention_sweep(db, settings=settings, now=NOW)

    assert report["chat_messages_deleted"] == 2
    assert report["conversations_deleted"] == 1
    assert db.get(Conversation, conv_id) is None, "an empty aged thread must not be left behind"
    assert _message_ids(db) == []


def test_an_unused_conversation_outside_the_window_is_removed(sweep_env) -> None:
    settings, db = sweep_env
    student = _seed_student(db)
    conv_id = _seed_conversation(db, student, created_days_ago=400, messages=[])
    fresh_id = _seed_conversation(db, student, created_days_ago=1, messages=[])

    report = run_retention_sweep(db, settings=settings, now=NOW)

    assert report["conversations_deleted"] == 1
    assert db.get(Conversation, conv_id) is None
    # A conversation created inside the window is untouched: the UI creates the
    # row before the first message is posted, so sweeping it would break the
    # very next request.
    assert db.get(Conversation, fresh_id) is not None


def test_feedback_pointers_are_detached_from_deleted_messages_only(sweep_env) -> None:
    """Feedback keeps the row and drops only the pointer into erased content.

    The detach runs inside the same chunk as the delete (the pre-fix ordering),
    and it must not touch a pointer at a message that survives the sweep.
    """
    settings, db = sweep_env
    student = _seed_student(db)
    conv_id = _seed_conversation(
        db,
        student,
        created_days_ago=400,
        messages=[("assistant", "old answer", 400), ("assistant", "recent answer", 1)],
    )
    messages = {
        content: mid
        for mid, content in db.execute(select(ChatMessage.id, ChatMessage.content)).all()
    }
    old_feedback = Feedback(user_id=student.user_id, message_id=messages["old answer"], rating=-1)
    live_feedback = Feedback(
        user_id=student.user_id, message_id=messages["recent answer"], rating=1
    )
    db.add_all([old_feedback, live_feedback])
    db.commit()

    run_retention_sweep(db, settings=settings, now=NOW)

    db.expire_all()
    assert db.get(Conversation, conv_id) is not None
    assert set(_message_ids(db)) == {messages["recent answer"]}
    rows = {row.id: row for row in db.execute(select(Feedback)).scalars()}
    assert set(rows) == {old_feedback.id, live_feedback.id}, "feedback history must survive"
    assert rows[old_feedback.id].message_id is None, "the pointer at erased content must be gone"
    assert rows[live_feedback.id].message_id == messages["recent answer"], (
        "a surviving message must keep its feedback pointer"
    )


def test_the_sweep_stays_idempotent_under_the_new_predicate(sweep_env) -> None:
    """A second run over the same data finds nothing left and counts zero."""
    settings, db = sweep_env
    student = _seed_student(db)
    _seed_conversation(
        db,
        student,
        created_days_ago=400,
        messages=[("user", "old", 400), ("user", "recent", 1)],
    )

    first = run_retention_sweep(db, settings=settings, now=NOW)
    second = run_retention_sweep(db, settings=settings, now=NOW)

    assert first["chat_messages_deleted"] == 1
    assert second["chat_messages_deleted"] == 0
    assert second["conversations_deleted"] == 0


# --- DAT-002: the sweep must not wedge on the SQL variable ceiling -----------


def _seed_aged_threads(settings: Settings, count: int) -> None:
    """``count`` conversations created 400 days ago, each with one aged message.

    Written through an engine of its own (executemany, small bindings) so the
    per-connection variable limit the sweep runs under never applies to setup.
    """
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    stamp = NOW - timedelta(days=400)
    with engine.begin() as conn:
        conn.execute(insert(Student), [{"id": 1, "name": "Kid", "class_level": 6}])
        conn.execute(
            insert(Conversation),
            [
                {"id": cid, "student_id": 1, "title": "t", "created_at": stamp}
                for cid in range(1, count + 1)
            ],
        )
        conn.execute(
            insert(ChatMessage),
            [
                {
                    "conversation_id": cid,
                    "role": "user",
                    "content": "q",
                    "created_at": stamp,
                }
                for cid in range(1, count + 1)
            ],
        )
    engine.dispose()


#: The largest statement the sweep may legitimately issue: one chunk of ids
#: plus the value the feedback-detach UPDATE writes.
MAX_BINDS = DELETE_CHUNK + 1


@pytest.fixture
def limited_engine(tmp_path):
    """A sweep engine whose connections refuse more than one chunk of binds.

    ``sqlite3.Connection.setlimit`` lowers ``SQLITE_LIMIT_VARIABLE_NUMBER`` per
    connection; the list's default 32766 is the ceiling a production sweep can
    really hit, but seeding 32767 rows in a unit test buys nothing: binding MORE
    than one chunk is the defect, so the limit is one chunk (+1 for the SET
    value of the detach UPDATE).
    """
    settings = _settings(tmp_path, name="dat002")
    engine = make_engine(settings)

    def _cap(dbapi_connection, _record) -> None:
        dbapi_connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, MAX_BINDS)

    event.listen(engine, "connect", _cap)
    binds: list[int] = []

    def _record(_conn, _cursor, _statement, parameters, _context, _executemany) -> None:
        if (
            isinstance(parameters, (list, tuple))
            and parameters
            and not isinstance(parameters[0], (list, tuple, dict))
        ):
            binds.append(len(parameters))

    event.listen(engine, "before_cursor_execute", _record)
    yield settings, engine, binds
    engine.dispose()


def test_the_sweep_drains_more_rows_than_the_variable_ceiling(tmp_path, limited_engine) -> None:
    """The wedge: more expired rows than any single statement may bind.

    Pre-fix this raises ``OperationalError: too many SQL variables`` on the
    first chunk (the whole id list is re-bound on every statement) and the
    retry is identical, so the sweep never drains. Post-fix every statement
    binds at most one chunk and the sweep empties the table.
    """
    settings, engine, binds = limited_engine
    seeded = DELETE_CHUNK + 1000
    _seed_aged_threads(settings, seeded)

    with make_session_factory(engine)() as db:
        dry = run_retention_sweep(db, settings=settings, dry_run=True, now=NOW)
        report = run_retention_sweep(db, settings=settings, now=NOW)
        remaining = (
            db.execute(select(func.count(Conversation.id))).scalar_one(),
            db.execute(select(func.count(ChatMessage.id))).scalar_one(),
        )

    assert dry["conversations_deleted"] == seeded
    assert dry["chat_messages_deleted"] == seeded
    assert report["conversations_deleted"] == seeded
    assert report["chat_messages_deleted"] == seeded
    assert remaining == (0, 0), "the sweep left expired rows behind"
    assert binds, "no statement was recorded; the bound-parameter guard is vacuous"
    assert max(binds) <= MAX_BINDS, (
        f"a single statement bound {max(binds)} variables; the id list must be "
        f"paged (DELETE_CHUNK={DELETE_CHUNK}), or the sweep wedges at the "
        f"engine ceiling and never drains"
    )
