"""Wave-2 data-layer pins: budget-reserve ledger, retention windows and
batching, and the attempts-JSON strip on erasure.

Bengali literals are Unicode escapes only (house rule for API tests).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import (
    AiUsage,
    AnswerLog,
    Assignment,
    Base,
    ClassRoom,
    QuizAttempt,
    School,
    ShortTest,
    Student,
    User,
)
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.gdpr import erase_account_everything
from bangla_gpt_api.services.retention import run_retention_sweep
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(tmp_path, db_name="wave2", **over) -> Settings:
    base = dict(env="test", database_url=engine_url(tmp_path, db_name), jwt_secret=SECRET)
    base.update(over)
    return Settings(**base)


def _engine(tmp_path, db_name="wave2"):
    engine = make_engine(_settings(tmp_path, db_name))
    Base.metadata.create_all(engine)
    return engine


def _session(tmp_path, db_name="wave2"):
    engine = make_engine(_settings(tmp_path, db_name))
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _any_user_id(db) -> int:
    """A ledger owner. create_app is never called on this database, so the
    boot-seeded admin does not exist here -- a plain user row is enough:
    the retention sweep only cares about the age of the ledger rows."""
    user = db.execute(
        select(User).where(User.email == "ledger-owner@example.com")
    ).scalar_one_or_none()
    if user is None:
        user = User(
            email="ledger-owner@example.com",
            password_hash="x",
            role="teacher",
            email_verified=True,
        )
        db.add(user)
        db.flush()
    return user.id


# --- DB-04/DB-03: the answer log and the AI ledger age, in bounded chunks ----


def test_retention_sweeps_the_ai_ledger_by_age(tmp_path) -> None:
    settings = _settings(tmp_path)
    with _session(tmp_path) as db, db.begin():
        now = datetime(2026, 10, 27, 12, 0, 0)
        old = now - timedelta(days=settings.ai_usage_retention_days + 5)
        admin = _any_user_id(db)
        db.add_all(
            [
                AiUsage(
                    user_id=admin,
                    route="tutor.ask",
                    model="mock",
                    prompt_tokens=10,
                    completion_tokens=5,
                    estimated_cost_usd=0.0,
                    created_at=old,
                ),
                AiUsage(
                    user_id=admin,
                    route="tutor.ask",
                    model="mock",
                    prompt_tokens=10,
                    completion_tokens=5,
                    estimated_cost_usd=0.0,
                    created_at=now,
                ),
            ]
        )

    with _session(tmp_path) as db:
        report = run_retention_sweep(db, settings=settings, now=datetime(2026, 10, 27, 12, 0, 0))
        remaining = list(db.execute(select(AiUsage)).scalars())

    assert report["ai_usage_deleted"] == 1, "only the expired ledger row is swept"
    assert len(remaining) == 1, "the in-window row survives"


def test_retention_sweep_is_idempotent(tmp_path) -> None:
    """A crash mid-chunks leaves completed chunks behind; the next sweep
    treats the survivors exactly like fresh expiry (expired-only)."""
    settings = _settings(tmp_path)
    with _session(tmp_path) as db, db.begin():
        admin = _any_user_id(db)
        old = datetime(2020, 1, 1, 0, 0, 0)
        db.add(
            AiUsage(
                user_id=admin,
                route="tutor.ask",
                model="mock",
                prompt_tokens=1,
                completion_tokens=1,
                estimated_cost_usd=0.0,
                created_at=old,
            )
        )

    with _session(tmp_path) as db:
        now = datetime(2026, 10, 27, 12, 0, 0)
        first = run_retention_sweep(db, settings=settings, now=now)
        second = run_retention_sweep(db, settings=settings, now=now)

    assert first["ai_usage_deleted"] == 1
    # the second run finds nothing expired anymore -- no double counting,
    # no resurrected rows, no drift between the report and reality
    assert second["ai_usage_deleted"] == 0


def test_answer_log_ages_on_its_own_timestamp(tmp_path) -> None:
    """DB-04: a graded answer older than the window is swept by the row's
    OWN timestamp. Two years ago this table had no timestamp at all."""
    settings = _settings(tmp_path)
    with _session(tmp_path) as db, db.begin():
        now = datetime(2026, 10, 27, 12, 0, 0)
        very_old = now - timedelta(days=800)
        owner = _any_user_id(db)
        student = Student(name="Answerer", class_level=6, user_id=None)
        db.add(student)
        db.flush()
        attempt = QuizAttempt(
            student_id=student.id,
            class_level=6,
            subject="science",
            status="graded",
        )
        db.add(attempt)
        db.flush()
        db.add(
            AnswerLog(
                attempt_id=attempt.id,
                seq=0,
                question_text="q",
                chosen=0,
                correct_index=1,
                is_correct=False,
                chapter="c",
                book="b",
                created_at=very_old,
            )
        )
        assert owner  # the ledger-owner user is unused here; keep setup single-purpose

    with _session(tmp_path) as db:
        report = run_retention_sweep(db, settings=settings, now=datetime(2026, 10, 27, 12, 0, 0))

    assert report["answer_log_deleted"] == 1


# --- DB-01: erasure prunes the erased child out of the attempts JSON --------


def test_erasure_strips_student_from_attempts_json(tmp_path) -> None:
    settings = _settings(tmp_path, db_name="erasure")
    engine = _engine(tmp_path, db_name="erasure")
    with make_session_factory(engine)() as db, db.begin():
        teacher = User(
            email="teacher@example.com",
            password_hash="x",
            role="teacher",
            email_verified=True,
        )
        child = User(
            email="child@example.com",
            password_hash="x",
            role="student",
            email_verified=True,
        )
        db.add_all([teacher, child])
        db.flush()
        school = School(name="Wave2 School", code="W2-SCH")
        db.add(school)
        db.flush()
        room = ClassRoom(school_id=school.id, class_level=6)
        db.add(room)
        db.flush()
        student = Student(name="Erased Child", class_level=6, user_id=child.id)
        db.add(student)
        db.flush()

        assignment = Assignment(
            teacher_id=teacher.id,
            subject="science",
            chapter="kosh",
            due_at=datetime(2026, 11, 30, 0, 0, 0),
        )
        db.add(assignment)
        db.flush()
        # the untyped payload the API itself writes (models: attempts JSON)
        assignment.attempts = [
            {"student_id": student.id, "attempt_id": None, "score": 80},
            {"student_id": 999_002, "attempt_id": None, "score": 40},
        ]
        short_test = ShortTest(
            teacher_id=teacher.id,
            classroom_id=room.id,
            subject="science",
            chapter="kosh",
        )
        db.add(short_test)
        db.flush()
        short_test.attempts = [{"student_id": student.id, "score": 10}]

        child_user_id = child.id
        child_student_id = student.id

    with make_session_factory(engine)() as db, db.begin():
        target = db.get(User, child_user_id)
        erase_account_everything(db, target)

    with make_session_factory(engine)() as db:
        assignment = db.execute(select(Assignment)).scalar_one()
        short_test = db.execute(select(ShortTest)).scalar_one()
        student_gone = db.execute(select(Student)).scalar_one_or_none()

    assert student_gone is None, "the child's profile row is erased"
    assert [e["student_id"] for e in assignment.attempts] == [999_002], (
        "the erased child's entry must be pruned, the sibling kept"
    )
    assert short_test.attempts == [], "short test attempts JSON must be pruned too"


# --- BE-01: the reserve ledger visible through a real request flow ----------


def test_reserve_ledger_row_keeps_budget_honest_under_provider_failure(
    tmp_path, monkeypatch
) -> None:
    """Parallel generations used to pass the budget gate off a ledger that
    only grew after completion; a failed generation left NO row. The
    reserve makes the in-flight and the failed spend real ledger lines."""
    import bangla_gpt_api.main as main_module
    from bangla_gpt_api.providers.base import LLMProvider as _Base
    from bangla_gpt_api.providers.base import ProviderError as _ProviderError

    class ExplodingProvider(_Base):
        name = "exploding"

        async def generate(self, prompt: str, *, system: str | None = None) -> str:
            raise _ProviderError("upstream down")

    settings = _settings(tmp_path, db_name="reserve")
    original = main_module.TutorService.__init__  # noqa: F841 - injected below

    def inject(self, *args, **kwargs):
        kwargs["provider"] = ExplodingProvider()
        kwargs["fast_provider"] = ExplodingProvider()
        original(self, *args, **kwargs)

    monkeypatch.setattr(main_module.TutorService, "__init__", inject)
    client = TestClient(create_app(settings))
    res = client.post(
        "/auth/register",
        json={
            "email": "reserve@example.com",
            "password": PASSWORD,
            "name": "Student",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "reserve@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    failed = client.post(
        "/tutor/ask",
        json={
            "question": "\u0995\u09cb\u09b7 \u0995\u09c0?",
            "class_level": 6,
            "subject": "science",
        },
        headers=headers,
    )
    assert failed.status_code == 502, failed.text

    engine = make_engine(settings)
    with make_session_factory(engine)() as db:
        rows = list(db.execute(select(AiUsage)).scalars())
    assert len(rows) == 1, "the failed generation owns exactly one ledger row"
    assert rows[0].prompt_tokens > 0 and rows[0].completion_tokens == 0


def test_failed_job_period_is_retryable(tmp_path) -> None:
    """BE-03: a crashed job used to leave its claim row indefinitely taken --
    a retention purge that failed halfway silently skipped the whole day.
    The FAILED outcome is retryable the same day; a finished one is not."""
    from bangla_gpt_api import jobs

    engine = _engine(tmp_path, db_name="jobruns")
    factory = make_session_factory(engine)
    with factory() as db, db.begin():
        pass  # create_all ran in _engine

    db = factory()
    try:
        assert jobs.claim_period(db, "retention_sweep", "2026-10-27") is True
        jobs.mark_period_failed(db, "retention_sweep", "2026-10-27", RuntimeError("boom"))
        # same-day retry after a crash: the whole point
        assert jobs.claim_period(db, "retention_sweep", "2026-10-27") is True
        jobs.finish_period(db, "retention_sweep", "2026-10-27", "convs=1 msgs=2")
        # a COMPLETED period stays claimed -- no accidental double-run
        assert jobs.claim_period(db, "retention_sweep", "2026-10-27") is False
    finally:
        db.close()
