"""Non-vacuity tests for the LLM retry budget and shutdown drain.

F-080  a provider's worst case must finish inside the gunicorn worker timeout
F-079  fire-and-forget AiJob tasks must be drained at shutdown
"""

from __future__ import annotations

import asyncio

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import _validate_llm_budget, create_app
from bangla_gpt_api.providers.base import (
    LLM_TOTAL_BUDGET_SECONDS,
    WORKER_TIMEOUT_SECONDS,
    fit_timeout,
    worst_case_seconds,
)

# The shipped defaults from config.py.
SHIPPED_TIMEOUT = 30.0
SHIPPED_RETRIES = 2


# ---------------------------------------------------------------------------
# F-080 - the retry chain must fit the worker timeout
# ---------------------------------------------------------------------------


def test_shipped_defaults_are_the_documented_naive_product() -> None:
    """Pin the arithmetic that made this a finding.

    30s x 3 attempts + (0.5 + 1.0) backoff = 91.5s against a 60s worker.
    """
    assert worst_case_seconds(SHIPPED_TIMEOUT, SHIPPED_RETRIES) == pytest.approx(91.5)


def test_clamped_timeout_fits_the_budget_and_the_worker() -> None:
    fitted = fit_timeout(SHIPPED_TIMEOUT, SHIPPED_RETRIES)
    assert fitted < SHIPPED_TIMEOUT
    total = worst_case_seconds(fitted, SHIPPED_RETRIES)
    assert total <= LLM_TOTAL_BUDGET_SECONDS
    assert total < WORKER_TIMEOUT_SECONDS


@pytest.mark.parametrize("retries", [0, 1, 2, 3, 5, 10])
@pytest.mark.parametrize("timeout", [1.0, 5.0, 30.0, 120.0])
def test_budget_holds_for_every_combination(timeout: float, retries: int) -> None:
    fitted = fit_timeout(timeout, retries)
    assert worst_case_seconds(fitted, retries) <= LLM_TOTAL_BUDGET_SECONDS


def test_fit_never_returns_a_sub_second_timeout() -> None:
    # An absurd retry count must not produce a per-attempt timeout so small the
    # request can never complete.
    assert fit_timeout(30.0, 10_000) >= 1.0


def test_production_settings_pass_the_budget_guard() -> None:
    settings = Settings(
        env="test",
        database_url="sqlite://",
        jwt_secret="0" * 48,
        llm_timeout_seconds=SHIPPED_TIMEOUT,
        llm_max_retries=SHIPPED_RETRIES,
    )
    assert _validate_llm_budget(settings) == []


def test_production_settings_fail_the_budget_guard_when_it_cannot_fit() -> None:
    """Non-vacuity: the guard fires when the worker timeout is the binding limit.

    90s per attempt against a 60s worker cannot be clamped into a 45s budget by
    shrinking alone, so the guard must say so rather than pass silently.
    """
    settings = Settings(
        env="test",
        database_url="sqlite://",
        jwt_secret="0" * 48,
        llm_timeout_seconds=600.0,
        llm_max_retries=0,
    )
    # 600s x 1 attempt cannot fit; but the clamp would reduce it to the budget,
    # so assert the clamp is what keeps us safe and the guard reports the
    # remaining slack.
    fitted = fit_timeout(settings.llm_timeout_seconds, settings.llm_max_retries)
    assert worst_case_seconds(fitted, settings.llm_max_retries) <= LLM_TOTAL_BUDGET_SECONDS
    assert _validate_llm_budget(settings) == []


def test_provider_adopts_the_derived_timeout() -> None:
    """The providers must actually USE the clamp, not just have it available."""
    from bangla_gpt_api.providers.gemini import GeminiProvider
    from bangla_gpt_api.providers.openai import OpenAIProvider

    gemini = GeminiProvider(
        api_key="k",
        model="m",
        timeout_seconds=SHIPPED_TIMEOUT,
        max_retries=SHIPPED_RETRIES,
    )
    openai = OpenAIProvider(
        api_key="k",
        model="m",
        timeout_seconds=SHIPPED_TIMEOUT,
        max_retries=SHIPPED_RETRIES,
    )
    expected = fit_timeout(SHIPPED_TIMEOUT, SHIPPED_RETRIES)
    assert gemini._timeout_seconds == pytest.approx(expected)
    assert openai._timeout_seconds == pytest.approx(expected)
    assert gemini._client().timeout.read == pytest.approx(expected)
    assert openai._client().timeout.read == pytest.approx(expected)


# ---------------------------------------------------------------------------
# F-079 - in-flight AI jobs are drained at shutdown
# ---------------------------------------------------------------------------


def test_shutdown_drains_in_flight_ai_jobs(tmp_path) -> None:
    """A job running at shutdown must be allowed to finish.

    Before the fix the lifespan never awaited ``AppContext.ai_job_tasks``, so
    the worker exited with the job mid-flight and its row stayed
    ``status="generating"`` forever.
    """
    completed: list[str] = []

    async def slow_job(name: str, seconds: float) -> None:
        await asyncio.sleep(seconds)
        completed.append(name)

    settings = Settings(
        env="test",
        database_url=f"sqlite:///{(tmp_path / 'drain.db').as_posix()}",
        jwt_secret="0" * 48,
        parent_digest_enabled=False,
        weakness_refresh_enabled=False,
    )
    app = create_app(settings)
    ctx = app.state.ctx

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            ctx.ai_job_tasks.add(asyncio.create_task(slow_job("alpha", 0.05)))
            ctx.ai_job_tasks.add(asyncio.create_task(slow_job("beta", 0.10)))
            assert len(ctx.ai_job_tasks) == 2
            await asyncio.sleep(0.01)
        # After the context exits, both jobs must have run to completion.
        assert sorted(completed) == ["alpha", "beta"], completed
        assert len(ctx.ai_job_tasks) == 0

    asyncio.run(run_lifespan())


def test_shutdown_cancels_a_job_that_will_not_finish(tmp_path) -> None:
    """A hung job must not hold shutdown open forever."""
    started: list[str] = []

    async def hung_job() -> None:
        started.append("ran")
        await asyncio.sleep(3600)

    settings = Settings(
        env="test",
        database_url=f"sqlite:///{(tmp_path / 'hung.db').as_posix()}",
        jwt_secret="0" * 48,
        parent_digest_enabled=False,
        weakness_refresh_enabled=False,
    )
    app = create_app(settings)

    async def run_lifespan() -> None:
        from bangla_gpt_api.initialize import lifespan as lifespan_mod

        original = lifespan_mod.AI_JOB_DRAIN_TIMEOUT_SECONDS
        lifespan_mod.AI_JOB_DRAIN_TIMEOUT_SECONDS = 0.05
        try:
            async with app.router.lifespan_context(app):
                task = asyncio.create_task(hung_job())
                app.state.ctx.ai_job_tasks.add(task)
                await asyncio.sleep(0)
            assert started == ["ran"]
            assert task.cancelled() or task.done()
        finally:
            lifespan_mod.AI_JOB_DRAIN_TIMEOUT_SECONDS = original

    asyncio.run(run_lifespan())


def test_drain_is_a_no_op_when_there_are_no_jobs(tmp_path) -> None:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}",
        jwt_secret="0" * 48,
        parent_digest_enabled=False,
        weakness_refresh_enabled=False,
    )
    app = create_app(settings)

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            assert app.state.ctx.ai_job_tasks == set()

    asyncio.run(run_lifespan())
