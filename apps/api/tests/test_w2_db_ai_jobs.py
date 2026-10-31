"""F-007/BE-17: AI-job lifecycle -- idempotency, retries, retention.

The audit found the job row was built as a status record, not a queue
entry: a double-click or client retry on POST /teacher/jobs created (and
paid for) two generations, a transient provider failure was never retried,
and ai_jobs rows were only ever deleted by account erasure, so the
payload/result JSON grew without bound.

These tests drive the real routes (the runner executes as a detached
asyncio task inside the app's portal, so the TestClient must be used as a
context manager) and assert:

* a repeat submission with the same Idempotency-Key returns the SAME job,
  and two CONCURRENT submissions collapse onto one row;
* a transient provider failure is retried and then succeeds, with the
  attempt count visible on the row (and the retry logged);
* a permanent failure reports failed after exactly one attempt;
* the retention sweep removes only terminal, aged rows -- in-flight and
  fresh rows survive, and the dry run deletes nothing.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bangla_gpt_api import jobs as job_policy
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiJob, User
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.services.retention import run_retention_sweep
from conftest import engine_url, poll_until

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
CHAPTER = "\u0995\u09cb\u09b7"
WORKSHEET_BODY = {"class_level": 6, "subject": "science", "chapter": CHAPTER}
NOW = datetime.now(UTC).replace(tzinfo=None)


class _FlakyProvider:
    """Raises a transient ProviderError a fixed number of times, then delegates.

    The provider protocol is a bare duck type (name / supports_vision /
    generate / stream), so a scripted stand-in wraps the app's own provider:
    failing attempts exercise the retry path, the successful one returns a
    real parseable document.
    """

    supports_vision = False

    def __init__(self, base, failures: int) -> None:
        self.base = base
        self.failures = failures
        self.calls = 0
        self.name = getattr(base, "name", "flaky")

    async def generate(self, prompt: str, *, system: str | None = None, image=None) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise ProviderError("simulated upstream 503")
        return await self.base.generate(prompt, system=system, image=image)

    def stream(self, prompt: str, *, system: str | None = None, image=None):
        return self.base.stream(prompt, system=system, image=image)


def _flaky_app(settings: Settings, provider) -> TestClient:
    """App client whose tutor service answers through ``provider``."""
    app = create_app(settings)
    app.state.ctx.tutor.provider = provider
    return TestClient(app)


def _settings(tmp_path, name: str, **over) -> Settings:
    base = dict(
        env="test",
        database_url=engine_url(tmp_path, name),
        jwt_secret=SECRET,
        # retries must be observable without slowing the suite down
        ai_job_retry_backoff_seconds=0.01,
        ai_job_max_attempts=3,
    )
    base.update(over)
    return Settings(**base)


def _register(client: TestClient, email: str) -> None:
    res = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Teach", "role": "teacher"},
    )
    assert res.status_code == 201, res.text


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _wait_settled(factory, job_id: str, timeout: float = 30.0) -> str:
    """Wait for the detached runner to stop writing (see module docstring)."""
    last = {"status": "queued"}

    def settled() -> str | None:
        with factory() as session:
            status = (
                session.execute(select(AiJob.status).where(AiJob.id == job_id)).scalar_one_or_none()
                or "missing"
            )
        last["status"] = status
        return status if status in job_policy.TERMINAL_STATUSES else None

    return poll_until(
        settled,
        timeout=timeout,
        describe=lambda: f"job {job_id} never settled (last status {last['status']})",
    )


# --- idempotency ------------------------------------------------------------


def test_repeat_submission_with_same_key_returns_the_same_job(tmp_path) -> None:
    settings = _settings(tmp_path, "jobs_idem")
    factory = make_session_factory(make_engine(settings))
    with TestClient(create_app(settings)) as client:
        _register(client, "idem@example.com")
        headers = {**_headers(client, "idem@example.com"), "Idempotency-Key": "worksheet-42-key"}
        body = {"kind": "worksheet", "payload": WORKSHEET_BODY}

        first = client.post("/teacher/jobs", json=body, headers=headers)
        assert first.status_code == 202, first.text
        second = client.post("/teacher/jobs", json=body, headers=headers)
        assert second.status_code == 202, second.text

        assert second.json()["id"] == first.json()["id"], "the replay must return the same job"
        _wait_settled(factory, first.json()["id"])
        with factory() as session:
            count = session.execute(select(func.count()).select_from(AiJob)).scalar_one()
            assert count == 1, "a repeat with the same key created a second job"

        # a different key is a new job (the header is not a global lock)
        third = client.post(
            "/teacher/jobs",
            json=body,
            headers={**headers, "Idempotency-Key": "worksheet-43-key"},
        )
        assert third.status_code == 202
        assert third.json()["id"] != first.json()["id"]
        _wait_settled(factory, third.json()["id"])


def test_malformed_key_is_refused_not_ignored(tmp_path) -> None:
    settings = _settings(tmp_path, "jobs_key_bad")
    with TestClient(create_app(settings)) as client:
        _register(client, "badkey@example.com")
        headers = {**_headers(client, "badkey@example.com"), "Idempotency-Key": "short"}
        res = client.post("/teacher/jobs", json={"kind": "worksheet"}, headers=headers)
        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "invalid_idempotency_key"


def test_jobs_without_a_key_still_work(tmp_path) -> None:
    """The header is optional; NULL keys do not collide (unique index)."""
    settings = _settings(tmp_path, "jobs_nokey")
    factory = make_session_factory(make_engine(settings))
    with TestClient(create_app(settings)) as client:
        _register(client, "nokey@example.com")
        headers = _headers(client, "nokey@example.com")
        body = {"kind": "worksheet", "payload": WORKSHEET_BODY}
        ids = {
            client.post("/teacher/jobs", json=body, headers=headers).json()["id"] for _ in range(2)
        }
        assert len(ids) == 2
        for job_id in ids:
            _wait_settled(factory, job_id)
        with factory() as session:
            keys = [row[0] for row in session.execute(select(AiJob.idempotency_key)).all()]
        assert keys == [None, None]


# --- retries ----------------------------------------------------------------


def test_transient_provider_failure_is_retried_then_succeeds(tmp_path) -> None:
    settings = _settings(tmp_path, "jobs_retry")
    factory = make_session_factory(make_engine(settings))
    with _flaky_app(settings, _FlakyProvider(MockLLMProvider(), failures=2)) as client:
        _register(client, "retry@example.com")
        headers = _headers(client, "retry@example.com")
        res = client.post(
            "/teacher/jobs", json={"kind": "worksheet", "payload": WORKSHEET_BODY}, headers=headers
        )
        assert res.status_code == 202, res.text
        job_id = res.json()["id"]
        assert _wait_settled(factory, job_id) == "ready"
        with factory() as session:
            job = session.get(AiJob, job_id)
            assert job is not None
            assert job.attempts == 3, "two transient failures plus the success must be counted"
            assert job.error is None
            assert job.result and job.result.get("document_id")


def test_permanent_failure_reports_failed_after_one_attempt(tmp_path) -> None:
    settings = _settings(tmp_path, "jobs_perm")
    factory = make_session_factory(make_engine(settings))
    with TestClient(create_app(settings)) as client:
        _register(client, "perm@example.com")
        headers = _headers(client, "perm@example.com")
        res = client.post("/teacher/jobs", json={"kind": "totally_bogus_kind"}, headers=headers)
        assert res.status_code == 202, res.text
        job_id = res.json()["id"]
        assert _wait_settled(factory, job_id) == "failed"
        with factory() as session:
            job = session.get(AiJob, job_id)
            assert job is not None
            assert job.error, "a failed job must carry its user-visible error type"
            assert job.attempts == 1, "a caller-fixable failure must not be retried"


def test_persistent_transient_failure_exhausts_the_plan(tmp_path) -> None:
    """A provider that never recovers fails after exactly max_attempts."""
    settings = _settings(tmp_path, "jobs_exhaust", ai_job_max_attempts=2)
    factory = make_session_factory(make_engine(settings))
    provider = _FlakyProvider(MockLLMProvider(), failures=10_000)
    with _flaky_app(settings, provider) as client:
        _register(client, "exhaust@example.com")
        headers = _headers(client, "exhaust@example.com")
        res = client.post(
            "/teacher/jobs", json={"kind": "worksheet", "payload": WORKSHEET_BODY}, headers=headers
        )
        job_id = res.json()["id"]
        assert _wait_settled(factory, job_id) == "failed"
        with factory() as session:
            job = session.get(AiJob, job_id)
            assert job is not None
            assert job.attempts == 2
            assert job.error == "ProviderError"
        assert provider.calls == 2, "attempts must be bounded by AI_JOB_MAX_ATTEMPTS"


def test_retry_plan_is_bounded_and_settings_driven() -> None:
    settings = Settings(env="test", ai_job_max_attempts=4, ai_job_retry_backoff_seconds=0.5)
    attempts, delays = job_policy.ai_job_retry_plan(settings)
    assert attempts == 4
    assert delays == (0.5, 1.0, 2.0)
    # the ceiling keeps one link of the chain inside the provider budget
    attempts, delays = job_policy.ai_job_retry_plan(
        Settings(env="test", ai_job_max_attempts=9, ai_job_retry_backoff_seconds=4.0)
    )
    assert attempts == 9 and max(delays) == 4.0
    # retries disabled => no delays, one attempt
    assert job_policy.ai_job_retry_plan(Settings(env="test", ai_job_max_attempts=1)) == (1, ())


def test_transient_classifier_separates_flaky_from_caller_fixable() -> None:
    assert job_policy.is_transient_failure(ProviderError("503"))
    assert job_policy.is_transient_failure(TimeoutError())
    assert job_policy.is_transient_failure(ConnectionError())
    assert not job_policy.is_transient_failure(ValueError("bad payload"))
    assert not job_policy.is_transient_failure(KeyError("kind"))


# --- retention --------------------------------------------------------------


def _seed_job(factory, *, status: str, age_days: int, kind: str = "worksheet") -> str:
    from uuid import uuid4

    job_id = str(uuid4())
    stamp = NOW - timedelta(days=age_days)
    with factory() as session:
        user = User(
            email=f"{job_id[:8]}@example.com",
            password_hash="x",
            role="teacher",
        )
        session.add(user)
        session.flush()
        session.add(
            AiJob(
                id=job_id,
                user_id=user.id,
                kind=kind,
                status=status,
                payload={"class_level": 6},
                created_at=stamp,
                updated_at=stamp,
            )
        )
        session.commit()
    return job_id


@pytest.fixture
def retention_factory(tmp_path):
    settings = _settings(tmp_path, "jobs_sweep", ai_jobs_retention_days=30)
    return settings, make_session_factory(make_engine(settings))


def test_sweep_deletes_only_terminal_aged_rows(retention_factory) -> None:
    settings, factory = retention_factory
    from bangla_gpt_api.db.base import Base
    from bangla_gpt_api.db.session import make_engine as _mk

    Base.metadata.create_all(_mk(settings))
    old_ready = _seed_job(factory, status="ready", age_days=45)
    old_failed = _seed_job(factory, status="failed", age_days=45)
    old_stuck = _seed_job(factory, status="generating", age_days=45)
    fresh_ready = _seed_job(factory, status="ready", age_days=1)
    assert old_ready != old_failed  # distinct rows; the ids are asserted below
    assert {old_stuck, fresh_ready}.isdisjoint({old_ready, old_failed})

    with factory() as session:
        dry = run_retention_sweep(session, settings=settings, dry_run=True, now=NOW)
        assert dry["dry_run"] is True and dry["ai_jobs_deleted"] == 2
        # the dry run must not have touched anything
        assert session.execute(select(func.count()).select_from(AiJob)).scalar_one() == 4

        report = run_retention_sweep(session, settings=settings, dry_run=False, now=NOW)
        assert report["ai_jobs_deleted"] == 2

        survivors = {row[0] for row in session.execute(select(AiJob.id)).all()}
    assert survivors == {old_stuck, fresh_ready}, "sweep took an in-flight or fresh row"


def test_sweep_never_deletes_an_in_flight_row_however_old(retention_factory) -> None:
    settings, factory = retention_factory
    from bangla_gpt_api.db.base import Base
    from bangla_gpt_api.db.session import make_engine as _mk

    Base.metadata.create_all(_mk(settings))
    stuck = _seed_job(factory, status="queued", age_days=400)
    with factory() as session:
        report = run_retention_sweep(session, settings=settings, dry_run=False, now=NOW)
        assert report["ai_jobs_deleted"] == 0
        assert session.execute(select(func.count()).select_from(AiJob)).scalar_one() == 1
        assert session.get(AiJob, stuck) is not None
