"""AUD-A2-15 / A9-03: bounded retries carry jitter.

Deterministic exponential backoff makes every replica that saw the same 503
retry at the same instant, which re-creates the overload the retry was for.
Pinned here:

* the delay for attempt n is drawn from [ceiling/2, ceiling] for the same
  exponential ceiling the old code used, so the worst case -- and therefore
  the fitted per-attempt timeout budget -- is unchanged;
* delays vary between calls (that IS the jitter) and never exceed the cap;
* both real providers sleep with the jittered delay on a retryable status;
* the chain is still bounded: ``worst_case_seconds`` remains a valid upper
  bound, so nothing can outgrow the worker timeout.
"""

from __future__ import annotations

import httpx
import pytest

from bangla_gpt_api.providers import base as base_module
from bangla_gpt_api.providers.base import (
    MAX_BACKOFF_SECONDS,
    backoff_total_seconds,
    retry_delay_seconds,
)
from bangla_gpt_api.providers.gemini import GeminiProvider
from bangla_gpt_api.providers.openai import OpenAIProvider


def _ceiling(attempt: int) -> float:
    return min(0.5 * (2**attempt), MAX_BACKOFF_SECONDS)


def test_delay_stays_inside_the_jitter_window() -> None:
    for attempt in range(6):
        for _ in range(20):
            delay = retry_delay_seconds(attempt)
            assert _ceiling(attempt) * 0.5 <= delay <= _ceiling(attempt)


def test_delays_are_jittered_not_deterministic() -> None:
    samples = {retry_delay_seconds(3) for _ in range(25)}
    assert len(samples) > 1, "a deterministic delay is the failure mode jitter exists to fix"
    assert min(samples) >= 0.25 * 8 and max(samples) <= 4.0


def test_jitter_never_extends_the_worst_case_budget() -> None:
    for retries in (0, 1, 2, 3, 8):
        ceiling_total = backoff_total_seconds(retries)
        observed = sum(_ceiling(n) for n in range(max(0, retries)))
        assert ceiling_total == pytest.approx(observed)
        # every draw is at or below its ceiling, so a full chain of draws
        # cannot exceed the budget the timeout fitter reserved for it
        for _ in range(5):
            assert sum(retry_delay_seconds(n) for n in range(retries)) <= ceiling_total


def test_negative_attempt_is_treated_as_zero() -> None:
    assert 0.25 <= retry_delay_seconds(-3) <= 0.5


@pytest.mark.asyncio
async def test_gemini_retry_sleeps_with_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    import bangla_gpt_api.providers.gemini as gemini

    slept: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": {"message": "over"}}, request=request)
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}, request=request
        )

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(gemini.asyncio, "sleep", fake_sleep)
    provider = GeminiProvider(
        api_key="k",
        model="gemini-3.1-flash-lite",
        timeout_seconds=5.0,
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )
    assert await provider.generate("q") == "ok"
    assert len(slept) == 1
    # attempt 0: deterministic backoff would be exactly 0.5s; jitter draws
    # from [0.25, 0.5] and the draw must come from the shared helper
    assert 0.25 <= slept[0] <= 0.5


@pytest.mark.asyncio
async def test_openai_retry_sleeps_with_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    import bangla_gpt_api.providers.openai as openai

    slept: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": {"message": "boom"}}, request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
            request=request,
        )

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(openai.asyncio, "sleep", fake_sleep)
    provider = OpenAIProvider(
        api_key="k",
        model="gpt-4o-mini",
        timeout_seconds=5.0,
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )
    assert await provider.generate("q") == "ok"
    assert len(slept) == 1 and 0.25 <= slept[0] <= 0.5


def test_the_helper_is_the_single_retry_policy_surface() -> None:
    # Providers must call the shared helper, not re-implement backoff inline.
    import inspect

    for module in ("gemini", "openai"):
        provider_module = __import__(f"bangla_gpt_api.providers.{module}", fromlist=["x"])
        text = inspect.getsource(provider_module)
        assert "retry_delay_seconds(attempt)" in text, module
        assert "2 ** attempt" not in text, f"{module} re-implements the backoff curve"


def test_retry_policy_constants_are_exported_from_the_boundary_module() -> None:
    assert (
        base_module.RETRY_POLICY == "full-jitter [ceiling/2, ceiling], ceiling = min(0.5*2^n, 4s)"
    )
