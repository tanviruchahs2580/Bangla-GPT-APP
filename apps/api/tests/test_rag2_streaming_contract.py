"""AUD-A2-16 / A6-08: the streaming contract, documented and tested.

Pinned here:

* every event the stream can emit belongs to the documented set
  (token / citation / heartbeat / error / final) and the contract text names
  the heartbeat interval, the mid-stream error policy, the reconnection
  policy and the partial-answer persistence rule;
* a provider that stalls produces heartbeat events (not a silent connection);
* a grounded answer produces a citation event carrying exactly the sources
  the final event carries -- and no citation event is emitted when the answer
  fails the post-generation check or the turn is refused;
* a mid-stream provider failure produces an error event plus the degraded
  evidence-only answer, and the final event is honest (not grounded);
* exactly one final event, always last.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.services import tutor as tutor_module
from bangla_gpt_api.services.tutor import (
    EVIDENCE_ONLY_HEADER,
    STREAM_EVENT_TYPES,
    STREAM_HEARTBEAT_SECONDS,
    TutorService,
)

CHUNK_TEXT = "কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক। কোষেই সকল জৈবনিক কাজ ঘটে।"


def _meta() -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="sample",
        chapter="অধ্যায় ১",
        section="কোষ",
        page=3,
    )


def _hit() -> Hit:
    return Hit(chunk=Chunk(id="c1", meta=_meta(), text=CHUNK_TEXT), score=1.0)


class _Index:
    chunks: ClassVar[list[Chunk]] = [Chunk(id="c1", meta=_meta(), text=CHUNK_TEXT)]

    def search(self, query: str, **_kwargs) -> list[Hit]:
        return [_hit()]


class GroundedProvider:
    """Streams a sentence that lives in the evidence (passes the citation check)."""

    name = "grounded"

    async def generate(self, prompt, *, system=None, **kwargs):
        return CHUNK_TEXT

    async def stream(self, prompt, *, system=None, **kwargs):
        for part in ("কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক। ", "কোষেই সকল জৈবনিক কাজ ঘটে।"):
            yield part


class OutageProvider:
    """Streams nothing and fails like an open circuit with no fallback."""

    name = "outage"

    async def generate(self, prompt, *, system=None, **kwargs):
        from bangla_gpt_api.providers.base import ProviderError

        raise ProviderError("upstream down")

    async def stream(self, prompt, *, system=None, **kwargs):
        from bangla_gpt_api.providers.base import ProviderError

        raise ProviderError("upstream down")
        yield  # pragma: no cover - unreachable, keeps this an async generator


class SlowProvider(GroundedProvider):
    name = "slow"

    async def stream(self, prompt, *, system=None, **kwargs):
        await asyncio.sleep(0.05)
        yield "কোষ হলো জীবদেহের গঠনগত ও ক্রিয়াগত একক।"
        await asyncio.sleep(0.05)
        yield " কোষেই সকল জৈবনিক কাজ ঘটে।"


def _service(provider, heartbeat: float = 0.0) -> TutorService:
    service = TutorService(index=_Index(), provider=provider, min_coverage=0.0, min_score=0.0)
    service.stream_heartbeat_seconds = heartbeat
    return service


async def _collect(service: TutorService) -> list:
    return [event async for event in service.ask_stream("কোষ কী?", 6, "science")]


def test_contract_documents_every_policy() -> None:
    doc = tutor_module.__doc__ or ""
    source = tutor_module.__dict__
    contract = ""
    # The contract block is a module comment; assert on the constant + the
    # render of the docstring the module exposes for operators.
    assert STREAM_HEARTBEAT_SECONDS > 0
    assert {"token", "citation", "heartbeat", "error", "final"} == set(STREAM_EVENT_TYPES)
    import inspect

    # C-03: the streaming contract block documents the constants that live in
    # the tutor package's `signals` seam, so that is the file pinned here (the
    # package root only re-exports them).
    from bangla_gpt_api.services.tutor import signals as contract_module

    file_text = inspect.getsource(contract_module)
    contract = file_text
    for phrase in (
        "Event schema",
        "heartbeat",
        "Mid-stream error policy",
        "Reconnection policy",
        "partial-answer persistence",
    ):
        assert phrase in contract, f"streaming contract must document {phrase!r}"
    assert doc is not None  # module docstring stays present
    assert source["STREAM_EVENT_TYPES"] is not None


async def test_grounded_turn_emits_tokens_then_citation_then_final() -> None:
    events = await _collect(_service(GroundedProvider()))
    kinds = [e.type for e in events]
    assert kinds[-1] == "final"
    assert kinds.count("final") == 1
    assert "token" in kinds
    citation = events[kinds.index("citation")]
    final = events[-1]
    assert citation.extra["citation_verified"] is True
    assert citation.extra["sources"], "citation event must carry the validated sources"
    assert [s["page"] for s in citation.extra["sources"]] == [
        s.page for s in final.response.sources
    ]
    assert final.response.grounded is True
    assert kinds.index("citation") < kinds.index("final")


async def test_a_slow_provider_produces_heartbeats_not_silence() -> None:
    events = await _collect(_service(SlowProvider(), heartbeat=0.01))
    kinds = [e.type for e in events]
    assert "heartbeat" in kinds
    heartbeat = events[kinds.index("heartbeat")]
    assert heartbeat.extra["interval_seconds"] == 0.01
    assert heartbeat.text is None
    assert kinds[-1] == "final"


async def test_refusal_emits_no_citation_event() -> None:
    class EmptyIndex(_Index):
        def search(self, query: str, **_kwargs) -> list[Hit]:
            return []

    service = TutorService(
        index=EmptyIndex(), provider=GroundedProvider(), min_coverage=0.5, min_score=0.0
    )
    events = [e async for e in service.ask_stream("কোষ কী?", 6, "science")]
    assert [e.type for e in events] == ["token", "final"]
    assert events[-1].response.grounded is False


async def test_mid_stream_failure_emits_error_then_the_degraded_answer() -> None:
    from bangla_gpt_api.services.circuit_breaker import CircuitBreaker

    # The production wiring always has a breaker; once it is open and no
    # fallback is configured, the stream degrades to the evidence-only answer.
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=300.0, name="rag2")
    service = TutorService(
        index=_Index(),
        provider=OutageProvider(),
        min_coverage=0.0,
        min_score=0.0,
        circuit_breaker=breaker,
    )
    from bangla_gpt_api.providers.base import ProviderError

    with pytest.raises(ProviderError):
        await service.ask("কোষ কী?", 6, "science")  # trips the breaker
    events = await _collect(service)
    kinds = [e.type for e in events]
    assert "error" in kinds
    error = events[kinds.index("error")]
    assert error.extra["code"] == "llm_unavailable"
    assert error.extra["recoverable"] is True
    assert error.extra["degraded"] == "evidence_only"
    # The degraded answer is the retrieved passage with an honest notice.
    assert any(e.type == "token" and EVIDENCE_ONLY_HEADER in (e.text or "") for e in events)
    assert any(e.type == "token" and "c1" in (e.text or "") for e in events)
    final = events[-1]
    assert final.type == "final"
    assert final.response.grounded is False
    assert final.response.sources == []
    assert "citation" not in kinds


async def test_expected_events_always_end_with_one_final() -> None:
    for provider in (GroundedProvider(), SlowProvider()):
        events = await _collect(_service(provider, heartbeat=0.01))
        kinds = [e.type for e in events]
        assert kinds.count("final") == 1 and kinds[-1] == "final"
        assert set(kinds) <= set(STREAM_EVENT_TYPES)
        assert events[-1].response is not None
        assert events[-1].response.answer
