"""Concurrency guarantees for unique-keyed get-or-create paths.

The class of defect these lock down (QA §6, top of the "schedule next"
list): seven sites hand-rolled get-or-create under a unique constraint by
reading the row and, when absent, INSERTing it. Two concurrent first-writers
both read "absent", both INSERT, and the loser raised an unhandled
``IntegrityError`` — answering 500 in the quiz and chat paths *after* the
business write had already been committed and billed, and silently losing
counter increments even when no error surfaced.

``test_get_or_create_recovers_from_the_insert_race`` drives the exact
interleaving deterministically with a ``before_flush`` listener (a rival
connection commits the row between the helper's lookup and its INSERT) —
no sleeps and no thread-scheduling luck. The thread-level tests then prove
the same property through the real service entry points.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db import models  # noqa: F401 -- registers tables on Base.metadata
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models import AiJob, DailyActivity
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.initialize.lifespan import (
    AI_JOB_ORPHAN_AGE_SECONDS,
    reap_orphaned_ai_jobs,
)
from bangla_gpt_api.services.activity import dhaka_date, record_activity
from bangla_gpt_api.services.upsert import get_or_create, increment

# Engine-coupled by design: this file drives fixtures through raw
# sqlite3 connections (audit H-02 follow-up), so it pins SQLite and stays
# out of the BGPT_TEST_DATABASE_URL parity lane.


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/upsert.db")
    Base.metadata.create_all(eng)
    return eng


def _activity_lookup(date_iso: str):
    return select(DailyActivity).where(
        DailyActivity.student_id == 1, DailyActivity.date == date_iso
    )


def _activity_defaults(date_iso: str) -> dict:
    return {"student_id": 1, "date": date_iso, "questions": 0, "quizzes": 0, "minutes": 0}


def test_get_or_create_returns_existing_row(engine) -> None:
    with Session(engine) as db:
        created_row, created = get_or_create(
            db,
            model=DailyActivity,
            lookup=_activity_lookup("2026-01-01"),
            defaults=_activity_defaults("2026-01-01"),
        )
        assert created is True
        db.commit()
        again, created_again = get_or_create(
            db,
            model=DailyActivity,
            lookup=_activity_lookup("2026-01-01"),
            defaults=_activity_defaults("2026-01-01"),
        )
        assert created_again is False
        assert again.id == created_row.id


def test_get_or_create_recovers_from_the_insert_race(engine) -> None:
    """The rival commits between the lookup and the INSERT; no 500 escapes."""
    with Session(engine) as db:
        fired = threading.Event()

        def rival_commits(session, flush_context, instances):
            if fired.is_set():
                return
            fired.set()
            with Session(engine) as other:
                other.add(
                    DailyActivity(
                        student_id=1, date="2026-01-01", questions=7, quizzes=0, minutes=0
                    )
                )
                other.commit()

        sa_event.listen(db, "before_flush", rival_commits)
        try:
            row, created = get_or_create(
                db,
                model=DailyActivity,
                lookup=_activity_lookup("2026-01-01"),
                defaults=_activity_defaults("2026-01-01"),
            )
        finally:
            sa_event.remove(db, "before_flush", rival_commits)

        assert fired.is_set(), "the rival never ran; the race was not exercised"
        assert created is False, "the helper inserted over a row a rival had committed"
        assert row.questions == 7, "the re-read did not return the rival's committed row"
        db.commit()
        assert len(db.execute(select(DailyActivity)).scalars().all()) == 1


def test_increment_is_database_side_addition(engine) -> None:
    with Session(engine) as db:
        row, _ = get_or_create(
            db,
            model=DailyActivity,
            lookup=_activity_lookup("2026-01-01"),
            defaults=_activity_defaults("2026-01-01"),
        )
        increment(
            db,
            model=DailyActivity,
            where=(DailyActivity.id == row.id,),
            deltas={"questions": 2, "quizzes": 0, "minutes": 3},
        )
        db.commit()
        fresh = db.execute(_activity_lookup("2026-01-01")).scalar_one()
        # quizzes was a zero delta and must not have been touched.
        assert (fresh.questions, fresh.quizzes, fresh.minutes) == (2, 0, 3)


def _seed_user_and_student(db: Session, *, user_id: int, student_id: int) -> None:
    """Fixtures for tests that go through make_engine (foreign_keys=ON).

    User must be flushed before Student: without a relationship() between
    the mappers, the ORM sorts a batch flush by mapper registration order,
    not by the raw FK — the app's own import path flushes user-first for the
    same reason.
    """
    from bangla_gpt_api.db.models import Student, User

    db.add(
        User(
            id=user_id,
            email=f"u{user_id}@example.test",
            password_hash="x",
            role="student",
            email_verified=True,
        )
    )
    db.flush()
    db.add(Student(id=student_id, user_id=user_id, name="Kid", class_level=6))
    db.flush()


def test_parallel_first_of_day_activity_counts_exactly_once_each(tmp_path) -> None:
    """Two simultaneous first-of-day records: one row, both increments.

    This is the double-click / two-tab scenario. The old body raised an
    unhandled IntegrityError on the losing INSERT (500 after the tutor reply
    was already committed), and its ORM ``+=`` could lose an increment; the
    new body must produce one row whose counters equal the sum of all calls.
    """
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/activity.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    factory = make_session_factory(make_engine(settings))
    with factory() as db:
        Base.metadata.create_all(db.get_bind())
        _seed_user_and_student(db, user_id=1, student_id=1)
        db.commit()

    workers = 4
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def call() -> None:
        db = factory()
        try:
            barrier.wait(5)
            record_activity(db, 1, questions=1, minutes=1)
        except BaseException as exc:  # noqa: BLE001 - recorded, asserted below
            with errors_lock:
                errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=call) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert not errors, f"record_activity raised under concurrency: {errors!r}"
    with factory() as db:
        rows = db.execute(select(DailyActivity)).scalars().all()
    assert len(rows) == 1, "a racing first-of-day insert created a duplicate row"
    assert (rows[0].questions, rows[0].minutes) == (workers, workers), (
        "increments were lost: expected "
        f"({workers}, {workers}), stored ({rows[0].questions}, {rows[0].minutes})"
    )
    assert rows[0].date == dhaka_date(datetime.now(UTC))


def test_reaper_fails_only_orphaned_jobs(tmp_path) -> None:
    """A SIGKILLed worker's rows resolve; a live-looking job is untouched."""
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/reaper.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    factory = make_session_factory(make_engine(settings))
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=AI_JOB_ORPHAN_AGE_SECONDS + 60)
    with factory() as db:
        Base.metadata.create_all(db.get_bind())
        _seed_user_and_student(db, user_id=1, student_id=1)
        db.add_all(
            [
                AiJob(
                    id="orphan", user_id=1, kind="worksheet", status="generating", created_at=old
                ),
                AiJob(
                    id="orphan2", user_id=1, kind="worksheet", status="validating", created_at=old
                ),
                AiJob(
                    id="live",
                    user_id=1,
                    kind="worksheet",
                    status="generating",
                    # young enough to be a job another worker is still running
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                ),
                AiJob(id="ready", user_id=1, kind="worksheet", status="ready", created_at=old),
            ]
        )
        db.commit()

    reaped = reap_orphaned_ai_jobs(factory)
    assert reaped == 2

    with factory() as db:
        by_id = {job.id: job for job in db.execute(select(AiJob)).scalars()}
    assert by_id["orphan"].status == "failed" and by_id["orphan"].error == "job_interrupted"
    assert by_id["orphan2"].status == "failed"
    assert by_id["live"].status == "generating", "a possibly-live job was failed"
    assert by_id["ready"].status == "ready"
