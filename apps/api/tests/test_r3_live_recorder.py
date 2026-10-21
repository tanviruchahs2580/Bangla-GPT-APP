"""A8-05: the live-run recorder's budget guard, resume and pacing, pinned.

The recorder is what makes the live evaluation affordable and honest: it must
refuse a call that would cross the owner's spend cap *before* sending it, must
serve an interrupted run from its own recordings without re-spending, and must
never record a failed call as an answer.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.evaluation.live_recorder import (
    BudgetedRecordingProvider,
    QuotaExhausted,
    SpendCapExceeded,
)
from bangla_gpt_api.providers.base import ProviderError
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.providers.replay import digest


class _FlakyProvider(MockLLMProvider):
    """Fails the first ``failures`` calls, then answers normally."""

    def __init__(self, failures: int, message: str = "Gemini request failed: transient") -> None:
        super().__init__()
        self.remaining_failures = failures
        self.message = message
        self.calls = 0

    async def generate(self, prompt: str, *, system=None, image=None, sampling=None) -> str:  # type: ignore[override]
        self.calls += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise ProviderError(self.message)
        return await super().generate(prompt, system=system, image=image, sampling=sampling)


@pytest.mark.asyncio
async def test_spend_cap_refuses_before_sending_the_call() -> None:
    inner = MockLLMProvider()
    # A cap of zero: the very first call must be refused, and the provider must
    # never see a request (the guard runs before the call).
    recorder = BudgetedRecordingProvider(inner, model="gemini-3.5-flash-lite", max_usd=0.0)
    with pytest.raises(SpendCapExceeded):
        await recorder.generate("a question", system="system")
    assert recorder.calls == 0
    assert recorder.records == []


@pytest.mark.asyncio
async def test_recorded_answers_come_from_resume_without_spending() -> None:
    inner = MockLLMProvider()
    prompt, system = "কোষ কী?", "system text"
    key = digest(prompt, system, None)
    resume = [
        {
            "digest": key,
            "model": "gemini-3.5-flash-lite",
            "prompt_chars": len(prompt),
            "answer": "recorded answer",
            "latency_ms": 12.0,
            "at": "2026-10-19T00:00:00+00:00",
        }
    ]
    recorder = BudgetedRecordingProvider(
        inner, model="gemini-3.5-flash-lite", max_usd=1.0, resume=resume
    )
    assert await recorder.generate(prompt, system=system) == "recorded answer"
    assert recorder.resumed == 1
    assert recorder.calls == 0
    assert recorder.spent_usd == 0.0
    assert len(recorder.records) == 1


@pytest.mark.asyncio
async def test_transient_error_is_retried_and_then_recorded() -> None:
    inner = _FlakyProvider(failures=2)
    recorder = BudgetedRecordingProvider(
        inner, model="gemini-3.5-flash-lite", max_usd=1.0, min_interval=0.0
    )
    recorder.BACKOFF_SECONDS = 0.0  # no waiting in the unit test
    answer = await recorder.generate("প্রশ্ন", system="system")
    assert answer
    assert recorder.retries == 2
    assert recorder.calls == 1  # only the successful call is accounted
    assert len(recorder.records) == 1


@pytest.mark.asyncio
async def test_quota_refusal_after_retries_is_named_not_swallowed() -> None:
    inner = _FlakyProvider(failures=99, message="Gemini API error 429: quota exceeded")
    recorder = BudgetedRecordingProvider(
        inner, model="gemini-3.5-flash-lite", max_usd=1.0, min_interval=0.0
    )
    recorder.BACKOFF_SECONDS = 0.0
    with pytest.raises(QuotaExhausted):
        await recorder.generate("প্রশ্ন", system="system")
    # A failed call is never recorded as an answer.
    assert recorder.records == []
    assert recorder.errors, "the failure must be visible in the run conditions"
