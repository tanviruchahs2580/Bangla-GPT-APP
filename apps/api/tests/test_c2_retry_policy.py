"""C-17: retry with jitter at every integration boundary, explicitly.

AUD-CD-20 / status-cd C-17 recorded three gaps: the provider backoff was
deterministic (``min(0.5 * 2**n, 4)``, so a fleet of replicas retries in
lockstep and re-creates the outage it is recovering from), the SMTP boundary
had a 15s timeout but no retry policy, and the DB boundary had
``pool_pre_ping`` plus a connect timeout but no retry policy at all.

The policy now lives in ``jobs.RetryPolicy`` (DB, SMTP, AiJob) and in
``providers/base.retry_delay_seconds`` (LLM), with the same jittered shape.
This module pins the policies themselves and, more importantly, the *wiring*:
that the providers really sleep the jittered value, that the ledger commit is
really retried on a transient failure and really not retried on a duplicate
claim, and that the digest job sends through the retrying SMTP sender.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from bangla_gpt_api import ai_jobs, jobs
from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import JobRun
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.providers import base as provider_base
from bangla_gpt_api.providers.gemini import GeminiProvider
from bangla_gpt_api.providers.openai import OpenAIProvider

SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def factory(tmp_path: Path):
    settings = Settings(
        env="test", database_url=f"sqlite:///{tmp_path}/retry.db", jwt_secret=SECRET
    )
    engine = make_engine(settings)
    init_db(engine)
    yield make_session_factory(engine), settings
    engine.dispose()


# ----------------------------------------------------------- the policies --


def test_policy_rejects_impossible_budgets() -> None:
    with pytest.raises(ValueError):
        jobs.RetryPolicy("bad", attempts=0, base_seconds=1, cap_seconds=1)
    with pytest.raises(ValueError):
        jobs.RetryPolicy("bad", attempts=2, base_seconds=0, cap_seconds=1)
    with pytest.raises(ValueError):
        jobs.RetryPolicy("bad", attempts=2, base_seconds=1, cap_seconds=-1)


def test_policy_delays_are_jittered_and_bounded() -> None:
    policy = jobs.RetryPolicy("test", attempts=4, base_seconds=1.0, cap_seconds=5.0)
    assert policy.max_retries == 3
    for attempt in range(5):
        ceiling = min(policy.base_seconds * (2**attempt), policy.cap_seconds)
        samples = [policy.delay_seconds(attempt) for _ in range(40)]
        assert all(ceiling * provider_base.JITTER_FLOOR <= s <= ceiling for s in samples)
        assert len(set(samples)) > 1, "jitter must actually vary between callers"
    assert policy.worst_case_seconds() == pytest.approx(1 + 2 + 4)


def test_the_three_boundary_policies_are_explicit() -> None:
    assert jobs.DB_RETRY_POLICY.name == "db"
    assert jobs.DB_RETRY_POLICY.attempts >= 2
    assert jobs.DB_RETRY_POLICY.worst_case_seconds() < 5.0  # a slow commit must not stall a request
    assert jobs.SMTP_RETRY_POLICY.name == "smtp"
    assert jobs.SMTP_RETRY_POLICY.attempts == 2
    assert ai_jobs.AI_JOB_RETRY_POLICY.attempts == ai_jobs.AI_JOB_MAX_ATTEMPTS
    # the policies all jitter through the same floor as the LLM boundary
    assert all(
        p.delay_seconds(0) <= p.base_seconds
        for p in (
            jobs.DB_RETRY_POLICY,
            jobs.SMTP_RETRY_POLICY,
            ai_jobs.AI_JOB_RETRY_POLICY,
        )
    )


# ------------------------------------------------------- retry primitives --


def test_retry_on_error_returns_the_first_success() -> None:
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        return "ok"

    assert jobs.retry_on_error(fn, policy=jobs.DB_RETRY_POLICY) == "ok"
    assert len(calls) == 1


def test_retry_on_error_retries_then_succeeds(monkeypatch) -> None:
    slept: list[float] = []

    def record_sleep(attempt: int, policy: jobs.RetryPolicy) -> float:
        slept.append(float(attempt))
        return 0.0

    monkeypatch.setattr(jobs, "_backoff_sleep", record_sleep)
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise OperationalError("db", {}, Exception("locked"))
        return "ok"

    assert (
        jobs.retry_on_error(fn, policy=jobs.DB_RETRY_POLICY, retry_on=(OperationalError,)) == "ok"
    )
    assert len(calls) == 3
    assert slept == [0, 1]


def test_retry_on_error_reraises_when_the_budget_is_spent(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "_backoff_sleep", lambda attempt, policy: 0.0)
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        raise OperationalError("db", {}, Exception("down"))

    with pytest.raises(OperationalError):
        jobs.retry_on_error(fn, policy=jobs.DB_RETRY_POLICY, retry_on=(OperationalError,))
    assert len(calls) == jobs.DB_RETRY_POLICY.attempts


def test_retry_on_error_does_not_burn_the_budget_on_other_errors(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "_backoff_sleep", lambda attempt, policy: 0.0)
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        raise IntegrityError("stmt", {}, Exception("duplicate"))

    with pytest.raises(IntegrityError):
        jobs.retry_on_error(fn, policy=jobs.DB_RETRY_POLICY, retry_on=(OperationalError,))
    assert len(calls) == 1, "a permanent error must not be retried"


def test_retry_until_true_stops_on_the_first_success(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "_backoff_sleep", lambda attempt, policy: 0.0)
    results = [False, True]

    assert jobs.retry_until_true(lambda: results.pop(0), policy=jobs.SMTP_RETRY_POLICY) is True
    assert results == []


def test_retry_until_true_reports_failure_after_the_budget(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "_backoff_sleep", lambda attempt, policy: 0.0)
    attempts: list[int] = []

    def always_false() -> bool:
        attempts.append(1)
        return False

    assert jobs.retry_until_true(always_false, policy=jobs.SMTP_RETRY_POLICY) is False
    assert len(attempts) == jobs.SMTP_RETRY_POLICY.attempts


# ------------------------------------------------------------ DB boundary --


def test_ledger_commit_retries_a_transient_operational_error(factory, monkeypatch) -> None:
    make_session, _settings = factory
    monkeypatch.setattr(jobs, "_backoff_sleep", lambda attempt, policy: 0.0)
    db = make_session()
    try:
        real_commit = db.commit
        failures = {"left": 1}

        def flaky_commit():
            if failures["left"]:
                failures["left"] -= 1
                raise OperationalError("UPDATE job_runs", {}, Exception("database is locked"))
            return real_commit()

        monkeypatch.setattr(db, "commit", flaky_commit)
        assert jobs.claim_period(db, "parent_digest", "2026-W50") is True

        # the retried attempt must commit the REAL row, not an empty transaction
        monkeypatch.undo()
        row = db.get(JobRun, ("parent_digest", "2026-W50"))
        assert row is not None and row.started_at is not None
    finally:
        db.close()


def test_ledger_claim_does_not_retry_a_duplicate(factory, monkeypatch) -> None:
    make_session, _settings = factory
    monkeypatch.setattr(jobs, "_backoff_sleep", lambda attempt, policy: 0.0)
    db = make_session()
    try:
        assert jobs.claim_period(db, "parent_digest", "2026-W51") is True
        calls: list[int] = []
        real_commit = db.commit

        def counting_commit():
            calls.append(1)
            return real_commit()

        monkeypatch.setattr(db, "commit", counting_commit)
        assert jobs.claim_period(db, "parent_digest", "2026-W51") is False
        assert len(calls) == 1, "the double-run signal must not be retried"
    finally:
        db.close()


# ----------------------------------------------------------- SMTP boundary --


def test_smtp_policy_retries_and_returns_the_mailers_verdict(factory, monkeypatch) -> None:
    _make_session, settings = factory
    monkeypatch.setattr(jobs, "_backoff_sleep", lambda attempt, policy: 0.0)
    calls: list[dict] = []
    verdicts = [False, True]

    def sender(cfg, *, to, subject, body):  # noqa: ANN001, ANN202 - mirrors mailer.send_mail
        calls.append({"to": to, "subject": subject, "body": body})
        return verdicts.pop(0)

    assert (
        jobs.send_mail_with_retry(
            settings, to="p@example.com", subject="S", body="B", sender=sender
        )
        is True
    )
    assert len(calls) == 2
    assert calls[0] == {"to": "p@example.com", "subject": "S", "body": "B"}


def test_smtp_policy_gives_up_after_its_budget(factory, monkeypatch) -> None:
    _make_session, settings = factory
    monkeypatch.setattr(jobs, "_backoff_sleep", lambda attempt, policy: 0.0)
    calls: list[int] = []

    def sender(cfg, *, to, subject, body):  # noqa: ANN001, ANN202
        calls.append(1)
        return False

    assert (
        jobs.send_mail_with_retry(
            settings, to="p@example.com", subject="S", body="B", sender=sender
        )
        is False
    )
    assert len(calls) == jobs.SMTP_RETRY_POLICY.attempts
    # the policy is jittered, not a fixed pause
    delays = {jobs.SMTP_RETRY_POLICY.delay_seconds(0) for _ in range(30)}
    assert len(delays) > 1


def test_digest_uses_the_retrying_sender_only_when_smtp_is_configured(factory) -> None:
    """The job path never turns a disabled relay into a retry storm."""
    make_session, _settings = factory
    from bangla_gpt_api.services import parent_digest

    captured: dict = {}
    real = parent_digest.run_weekly_digest

    def spy(settings, db, *, sender=None, now=None):  # noqa: ANN001, ANN202
        captured["sender"] = sender
        return real(settings, db, sender=sender, now=now)

    parent_digest.run_weekly_digest = spy
    try:
        from datetime import datetime

        sunday = datetime(2026, 9, 6, 16, 30)

        plain = Settings(env="test", jwt_secret=SECRET)
        jobs.run_weekly_digest(make_session, plain, now=sunday)
        assert captured["sender"] is None, "no SMTP configured -> the digest keeps skipping"

        with_smtp = Settings(
            env="test",
            jwt_secret=SECRET,
            smtp_enabled=True,
            smtp_host="smtp.example.com",
            smtp_from="bot@example.com",
        )
        jobs.run_weekly_digest(make_session, with_smtp, now=datetime(2026, 9, 13, 16, 30))
        assert captured["sender"] is jobs.send_mail_with_retry
    finally:
        parent_digest.run_weekly_digest = real


# ------------------------------------------------------------- LLM wiring --


class _FakeAsyncio:
    """Records the sleeps the provider asks for, without actually sleeping."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)


def _gemini_retry_transport() -> httpx.MockTransport:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                503,
                json={"error": {"code": 503, "message": "backend error", "status": "UNAVAILABLE"}},
                request=request,
            )
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            request=request,
        )

    return httpx.MockTransport(handler)


def _openai_retry_transport() -> httpx.MockTransport:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                503,
                json={"error": {"code": 503, "message": "backend error"}},
                request=request,
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=request,
        )

    return httpx.MockTransport(handler)


def _build_gemini(transport: httpx.MockTransport) -> GeminiProvider:
    return GeminiProvider(
        api_key="k", model="m", timeout_seconds=5.0, max_retries=1, transport=transport
    )


def _build_openai(transport: httpx.MockTransport) -> OpenAIProvider:
    return OpenAIProvider(
        api_key="k", model="m", timeout_seconds=5.0, max_retries=1, transport=transport
    )


@pytest.mark.parametrize(
    "build, module_name, transport_factory",
    [
        (_build_gemini, "bangla_gpt_api.providers.gemini", _gemini_retry_transport),
        (_build_openai, "bangla_gpt_api.providers.openai", _openai_retry_transport),
    ],
    ids=["gemini", "openai"],
)
def test_provider_retry_sleep_is_the_jittered_policy_value(
    monkeypatch, build, module_name, transport_factory
) -> None:
    """The providers must sleep ``retry_delay_seconds``, not a fixed 0.5s.

    Both halves are pinned at once: the value comes from the shared jitter
    helper (spied ``random.uniform`` bounds), and the provider really awaits
    that value (recorded sleeps). A deterministic backoff would make every
    replica of the API retry a 503 at the same instant.
    """
    import importlib

    draws: list[tuple[float, float]] = []
    sentinel = 0.375

    class _SpyRng:
        """Wraps the provider's jitter RNG: records the bounds, fixes the draw."""

        def uniform(self, low: float, high: float) -> float:
            draws.append((low, high))
            return sentinel

    monkeypatch.setattr(provider_base, "_JITTER_RNG", _SpyRng())
    fake_asyncio = _FakeAsyncio()
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "asyncio", fake_asyncio)

    provider = build(transport_factory())

    async def run() -> str:
        return str(await provider.generate("q"))

    assert asyncio.run(run()) == "ok"
    assert draws == [(0.25, 0.5)], "the LLM boundary must draw its delay from the jitter helper"
    assert fake_asyncio.sleeps == [sentinel], "the provider must await the jittered delay"


def test_provider_jitter_helper_is_bounded_and_varied() -> None:
    values = [provider_base.retry_delay_seconds(0) for _ in range(40)]
    assert all(0.25 <= v <= 0.5 for v in values)
    assert len(set(values)) > 1
    # the declared total-budget helper stays a valid upper bound
    assert sum(provider_base.retry_delay_seconds(n) for n in range(2)) <= (
        provider_base.backoff_total_seconds(2)
    )
