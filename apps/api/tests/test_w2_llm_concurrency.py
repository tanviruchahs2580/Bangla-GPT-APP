"""Generation concurrency cap and usage hygiene (LLM-11 / F-117).

Request-rate limits bound how many turns start per minute; nothing bounded how
many provider calls run at once, so parallel streams could exhaust the quota
and the worker's budget. These tests pin the bound, the refusal envelope, and
the release of slots on failure -- a leak here would degrade the worker slowly
and invisibly.
"""

from __future__ import annotations

import asyncio
import contextlib

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import (
    GENERATION_BUSY_ANSWER,
    MAX_CONCURRENT_GENERATIONS,
    TutorService,
)

_QUESTION = "কোষ কী?"


class _SlowProvider(MockLLMProvider):
    """Provider that blocks until released, so the cap can be observed."""

    def __init__(self) -> None:
        self.entered = 0
        self.release = asyncio.Event()

    async def generate(self, prompt, *, system=None, image=None):  # type: ignore[override]
        self.entered += 1
        await self.release.wait()
        return await super().generate(prompt, system=system, image=image)


def _tutor(provider, *, cap: int, timeout: float = 0.05) -> TutorService:
    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    return TutorService(
        index=index,
        provider=provider,
        term_stats=index.term_stats,
        max_concurrent_generations=cap,
        generation_queue_timeout=timeout,
    )


def test_cap_refuses_the_call_that_exceeds_it() -> None:
    provider = _SlowProvider()
    tutor = _tutor(provider, cap=1)

    async def scenario() -> tuple[object, object]:
        first = asyncio.create_task(tutor.ask(_QUESTION, 6, "science"))
        await asyncio.sleep(0.05)  # let the first turn take the slot
        second = await tutor.ask(_QUESTION, 6, "science")
        provider.release.set()
        return await first, second

    first_response, second_response = asyncio.run(scenario())
    assert first_response.grounded is True  # type: ignore[attr-defined]
    assert second_response.grounded is False  # type: ignore[attr-defined]
    assert second_response.refused_reason == "ai_busy"  # type: ignore[attr-defined]
    assert second_response.answer == GENERATION_BUSY_ANSWER  # type: ignore[attr-defined]
    assert provider.entered == 1
    # A refused admission must not corrupt the semaphore: the lane serves the
    # next turn once the holder is done.
    tutor.provider = MockLLMProvider()
    assert asyncio.run(tutor.ask(_QUESTION, 6, "science")).grounded is True


def test_slot_is_released_after_a_successful_turn() -> None:
    provider = MockLLMProvider()
    tutor = _tutor(provider, cap=1)
    for _ in range(3):
        response = asyncio.run(tutor.ask(_QUESTION, 6, "science"))
        assert response.grounded is True


def test_slot_is_released_after_a_provider_failure() -> None:
    class _FailingProvider(MockLLMProvider):
        async def generate(self, prompt, *, system=None, image=None):  # type: ignore[override]
            raise RuntimeError("provider exploded")

    tutor = _tutor(_FailingProvider(), cap=1)
    for _ in range(2):
        with contextlib.suppress(RuntimeError):
            asyncio.run(tutor.ask(_QUESTION, 6, "science"))
    # The cap is still usable: a leaked slot would refuse the next turn.
    tutor.provider = MockLLMProvider()
    assert asyncio.run(tutor.ask(_QUESTION, 6, "science")).grounded is True


def test_cap_is_positive_by_default() -> None:
    assert MAX_CONCURRENT_GENERATIONS > 0
    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    tutor = TutorService(index=index, provider=MockLLMProvider(), term_stats=index.term_stats)
    assert tutor.max_concurrent_generations == MAX_CONCURRENT_GENERATIONS


def test_cap_of_zero_disables_the_bound_explicitly() -> None:
    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    tutor = TutorService(
        index=index,
        provider=MockLLMProvider(),
        term_stats=index.term_stats,
        max_concurrent_generations=0,
    )
    assert tutor._generation_slots is None
    assert asyncio.run(tutor.ask(_QUESTION, 6, "science")).grounded is True


def test_streaming_turn_refuses_when_the_lane_is_saturated() -> None:
    provider = _SlowProvider()
    tutor = _tutor(provider, cap=1)

    async def scenario() -> list[tuple[str, object]]:
        events: list[tuple[str, object]] = []
        first = asyncio.create_task(_drain(tutor, events))
        await asyncio.sleep(0.05)
        second: list[tuple[str, object]] = []
        await _drain(tutor, second)
        provider.release.set()
        await first
        return second

    second_events = asyncio.run(scenario())
    finals = [event for kind, event in second_events if kind == "final"]
    assert finals and finals[0].grounded is False  # type: ignore[attr-defined]
    assert finals[0].refused_reason == "ai_busy"  # type: ignore[attr-defined]


async def _drain(tutor: TutorService, sink: list[tuple[str, object]]) -> None:
    async for event in tutor.ask_stream(_QUESTION, 6, "science"):
        sink.append((event.type, event.response if event.type == "final" else event.text))
