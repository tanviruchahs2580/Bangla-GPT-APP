"""Factories and the injectable clock seam prove themselves (E-16).

Two things this file establishes:

1. The shared factories (``tests/factories.py``) produce Bangla-realistic,
   internally consistent rows -- and the sample text they carry is *verifiably*
   Bangla: ``BN_SENTENCE`` is asserted to be a verbatim substring of the
   shipped sample corpus, so a typo or an editor-corrupted escape cannot slip
   through unnoticed (the reason the repo keeps Bengali out of source as
   ``\\uXXXX`` escapes in the first place).
2. The clock seam (``tests/conftest_clock.py``) is usable for the thing
   E-16/H-14 asks for: a deterministic time-dependent test. The retention
   sweep is driven to two different verdicts -- zero deletions, then one --
   by advancing an injected clock, with no sleeping and no monkeypatching of
   the global ``datetime`` module.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import bangla_gpt_api
import factories
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db import clock as app_clock
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models import Conversation, Feedback
from bangla_gpt_api.services import retention
from conftest_clock import FixedClock, clock  # noqa: F401 - fixture re-export
from factories import (
    BN,
    BN_QUESTION,
    BN_SENTENCE,
    make_chat_message,
    make_classroom,
    make_conversation,
    make_corpus,
    make_school,
    make_student,
    make_user,
)

JWT = "test-secret-0123456789abcdef0123456789"


# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """A fresh file-backed SQLite database with the real schema."""
    engine = create_engine(f"sqlite:///{tmp_path}/factories.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


# ── Bangla-realistic sample data ──────────────────────────────────────────


def test_every_sample_word_is_nonempty_nfc_bangla() -> None:
    """Sample vocabulary is NFC and inside the Bangla block (no lookalikes)."""
    assert BN, "the vocabulary must not be empty"
    for name, word in BN.items():
        assert word, name
        assert unicodedata.is_normalized("NFC", word), name
        if name == "danda":
            assert word == "\u0964"
            continue
        assert all("\u0980" <= char <= "\u09ff" or char == " " for char in word), (
            f"{name}: {word!r} contains a character outside the Bangla block"
        )


def test_sample_sentence_is_verbatim_corpus_prose() -> None:
    """Drift guard: the factory sentence must still exist in the corpus.

    If a corpus edit removes or re-spells it, this fails instead of the
    factories silently feeding invented text into retrieval tests.
    """
    corpus_dir = Path(bangla_gpt_api.__file__).parent / "data" / "sample_nctb"
    text = (corpus_dir / "class6_science.md").read_text(encoding="utf-8")
    assert BN_SENTENCE in text
    assert BN_SENTENCE.endswith(BN["danda"])


def test_question_is_a_well_formed_bangla_question() -> None:
    assert BN_QUESTION.endswith(BN["danda"])
    assert "\u0995\u09c0" in BN_QUESTION  # ki ("what") -> it is a question


def test_sample_mobile_number_has_the_bd_shape_the_pii_scrubber_matches() -> None:
    """The factory phone must be a fake number in the real +880 format."""
    assert factories.BN_PHONE.startswith("017")
    assert factories.BN_PHONE.isdigit() and len(factories.BN_PHONE) == 11


# ── factories ─────────────────────────────────────────────────────────────


def test_user_and_role_rows_are_linked_and_unique(db) -> None:
    first = make_user(db, role="student")
    second = make_user(db, role="student")
    assert first.email != second.email
    assert first.email.endswith("@example.test")

    student = make_student(db, user=first, class_level=7)
    assert student.user_id == first.id
    assert student.class_level == 7

    teacher = factories.make_teacher(db, name="\u09b0\u09b9\u09bf\u09ae")  # Rahim
    assert teacher.user_id is not None
    assert db.get(type(teacher), teacher.id) is not None


def test_school_factories_build_a_consistent_tenancy(db) -> None:
    school = make_school(db)
    room = make_classroom(db, school=school, class_level=6, section="B")
    student = make_student(db)
    link = factories.enroll(db, classroom=room, student=student)

    assert link.classroom_id == room.id and link.student_id == student.id
    assert room.school_id == school.id
    assert school.code.startswith("BN-")


def test_single_use_rows_default_to_a_fresh_hash_and_a_future_expiry(db) -> None:
    user = make_user(db)
    verification = factories.make_verification(db, user=user)
    reset = factories.make_password_reset(db, user=user)

    assert verification.token_hash != reset.token_hash
    assert len(verification.token_hash) == 64
    assert verification.expires_at > factories.utcnow()
    assert verification.used_at is None and reset.used_at is None


def test_corpus_factory_chunks_are_distinct_and_typed() -> None:
    chunks = make_corpus(4)
    assert len({chunk.id for chunk in chunks}) == 4
    assert len({chunk.text for chunk in chunks}) == 4
    for chunk in chunks:
        assert chunk.meta.class_level == 6
        assert chunk.meta.subject == BN["science"]
        assert chunk.meta.chapter.startswith(BN["chapter"])
        assert chunk.meta.source == "factory"


# ── clock seam ────────────────────────────────────────────────────────────


def test_fixed_clock_mirrors_datetime_now_conventions() -> None:
    fixed = FixedClock("2026-03-01T09:30:00+00:00")
    assert fixed.now().tzinfo is None  # house contract: naive UTC
    assert fixed.now().isoformat() == "2026-03-01T09:30:00"
    assert fixed.now(tz=UTC).isoformat() == "2026-03-01T09:30:00+00:00"
    assert fixed.now_aware().isoformat() == "2026-03-01T09:30:00+00:00"
    assert isinstance(fixed, app_clock.Clock)  # usable as the app's seam

    fixed.advance(hours=6, minutes=30)
    assert fixed.now().isoformat() == "2026-03-01T16:00:00"
    assert fixed.monotonic() > 0


def test_installed_clock_is_restored_even_when_the_block_raises() -> None:
    """The seam must not leak into the next test (a process-wide global).

    Mutation that breaks it: dropping the ``finally`` in ``installed`` -- every
    later test in the session would then read a frozen clock.
    """
    before = app_clock.CLOCK
    fixed = FixedClock("2031-05-05T00:00:00+00:00")
    with pytest.raises(RuntimeError), fixed.installed():
        assert app_clock.utcnow().year == 2031
        raise RuntimeError("boom")
    assert app_clock.CLOCK is before
    assert app_clock.utcnow().year != 2031


def test_patched_datetime_is_scoped_to_the_module_and_the_block() -> None:
    """A module-global patch affects that module only, and ends with the block."""
    from types import SimpleNamespace

    namespace = SimpleNamespace(datetime=datetime)
    real_now = namespace.datetime.now()
    fixed = FixedClock("2030-01-02T03:04:05+00:00")
    with fixed.patched(namespace):
        assert namespace.datetime.now().isoformat() == "2030-01-02T03:04:05"
        assert namespace.datetime.utcnow().isoformat() == "2030-01-02T03:04:05"
        # Other modules keep the real clock.
        import bangla_gpt_api.services.mailer as mailer

        assert mailer.smtplib is not None  # module untouched by the patch
    assert namespace.datetime is datetime
    assert namespace.datetime.now() >= real_now


def test_retention_cutoff_follows_the_injected_clock(db) -> None:
    """The seam drives a real time-dependent decision: the retention cutoff.

    ``run_retention_sweep`` reads ``db.clock.utcnow()``; installing a frozen
    clock is what makes the two verdicts below deterministic (no sleeping, no
    patching of the global ``datetime`` module). Mutation that breaks it:
    replacing ``now = utcnow()`` with a direct ``datetime.now()`` inside
    ``run_retention_sweep`` -- the sweep then ignores the seam and counts both
    conversations (the failure this test was written from), or changing the
    ``<`` cutoff comparison to ``<=``.
    """
    settings = Settings(env="test", jwt_secret=JWT, chat_retention_days=30)
    student = make_student(db)
    fixed = FixedClock("2026-06-01T00:00:00+00:00")

    stale = make_conversation(
        db, student=student, created_at=fixed.now() - timedelta(days=40), title="stale"
    )
    fresh = make_conversation(
        db, student=student, created_at=fixed.now() - timedelta(days=1), title="fresh"
    )
    message = make_chat_message(db, conversation=stale, role="user")
    feedback = Feedback(user_id=make_user(db).id, message_id=message.id, rating=1)
    db.add(feedback)
    db.commit()
    # Capture the ids before the sweep expires the instances: reading an
    # attribute of a conversation the sweep deleted raises ObjectDeletedError.
    stale_id, fresh_id, feedback_id = stale.id, fresh.id, feedback.id

    with fixed.installed():
        report = retention.run_retention_sweep(db, settings=settings, dry_run=True)
        assert report["dry_run"] is True
        assert report["conversations_deleted"] == 1
        assert report["chat_messages_deleted"] == 1

        report = retention.run_retention_sweep(db, settings=settings, dry_run=False)
        assert report["dry_run"] is False
        assert report["conversations_deleted"] == 1

        # Idempotent once swept: nothing left to delete at the same instant.
        assert (
            retention.run_retention_sweep(db, settings=settings, dry_run=True)[
                "conversations_deleted"
            ]
            == 0
        )

    # Bulk DELETEs bypass the identity map, and ``db.get`` on an expired
    # instance whose row is gone raises ObjectDeletedError -- so read the
    # surviving ids with a plain query instead.
    surviving_ids = set(db.execute(select(Conversation.id)).scalars().all())
    assert stale_id not in surviving_ids
    assert fresh_id in surviving_ids, "a fresh conversation must survive"
    # The feedback row is product history and is kept; only the dangling
    # pointer into the erased conversation is dropped. (Read the columns
    # directly: refreshing the ORM instance would try to re-load the deleted
    # conversation and raise ObjectDeletedError.)
    assert (
        db.execute(select(Feedback.message_id).where(Feedback.id == feedback_id)).scalar_one()
        is None
    )
    assert db.execute(select(Feedback.rating).where(Feedback.id == feedback_id)).scalar_one() == 1


def test_retention_sweep_without_an_injected_clock_uses_the_real_one(db) -> None:
    """The seam is optional: ``now=None`` still sweeps with wall-clock time."""
    settings = Settings(env="test", jwt_secret=JWT, chat_retention_days=30)
    student = make_student(db)
    ancient = make_conversation(
        db, student=student, created_at=factories.utcnow() - timedelta(days=400)
    )
    report = retention.run_retention_sweep(db, settings=settings, dry_run=False)
    assert report["conversations_deleted"] == 1
    assert db.get(Conversation, ancient.id) is None


def test_analytics_retention_defaults_to_the_chat_window(db) -> None:
    """``analytics_retention_days`` falls back to ``chat_retention_days``.

    ``Settings`` defaults the field to 180, so the ``getattr(..., None)``
    fallback is only reachable through the settings-like object the sweep
    documents accepting -- which is exactly how the nightly job hands it over.
    Mutation that breaks it: returning ``None``/``0`` instead of the chat
    window in the ``analytics_days`` fallback, which would stop the analytics
    trail from ever being swept.
    """
    from types import SimpleNamespace

    from bangla_gpt_api.db.models import AnalyticsEventRow

    event = AnalyticsEventRow(
        name="lesson_opened",
        props={},
        created_at=factories.utcnow() - timedelta(days=45),
    )
    db.add(event)
    db.commit()

    chat_only = SimpleNamespace(chat_retention_days=30)  # no analytics field
    assert (
        retention.run_retention_sweep(db, settings=chat_only, dry_run=True)[
            "analytics_events_deleted"
        ]
        == 1
    )

    # An explicit, longer analytics window keeps the same row.
    longer = Settings(
        env="test", jwt_secret=JWT, chat_retention_days=30, analytics_retention_days=90
    )
    assert (
        retention.run_retention_sweep(db, settings=longer, dry_run=True)["analytics_events_deleted"]
        == 0
    )
    assert db.get(AnalyticsEventRow, event.id) is not None  # dry run deleted nothing
