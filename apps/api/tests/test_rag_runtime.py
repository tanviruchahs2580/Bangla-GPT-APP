"""Runtime-hardening tests for the tutor's hot path.

Three behaviours are pinned here so a later refactor cannot silently undo
them (each addresses a measured production risk, not style):

* *Event-loop freedom* — retrieval is synchronous CPU work over the corpus;
  it must run off the event loop (asyncio.to_thread), or one slow search
  freezes every concurrent SSE stream on the worker.
* *RAG hot-path observability* — retrieval latency, gate verdicts, refusal
  reasons and citation checks are Prometheus series (the HighRAGRefusalRate /
  RAGCitationCheckFailures alerts read them); a refusal that is invisible in
  /metrics is a regression.
* *Follow-up retrieval* — a short conversational follow-up ("এটা আবার") has
  no retrievable subject, so the prior user turn's content terms are
  appended; rich questions and deliberate search_query overrides are never
  rewritten.

Also pinned: the streaming path's refusal contract matches the non-stream
path (``citation_verified is None`` — the schema's "not applicable", not
``False``).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from bangla_gpt_api.metrics import REGISTRY
from bangla_gpt_api.providers.base import LLMProvider
from bangla_gpt_api.services.tutor import TutorService


class _Stub(LLMProvider):
    name = "stub"

    async def generate(self, prompt, *, system=None, **kwargs):  # noqa: ANN001
        return "উত্তর"

    async def stream(self, prompt, *, system=None, **kwargs):  # noqa: ANN001
        yield "উত্তর"


class _RecordingIndex:
    """Returns no hits (so the gate always refuses) but records every query."""

    def __init__(self, *, search_delay: float = 0.0) -> None:
        self.queries: list[str] = []
        self.search_delay = search_delay
        self.chunks: list[Any] = []

    def search(self, query: str, **_kwargs: Any) -> list:
        if self.search_delay:
            time.sleep(self.search_delay)
        self.queries.append(query)
        return []


def _counter_value(name: str, labels: dict[str, str] | None = None) -> float | None:
    return REGISTRY.get_sample_value(name, labels or {})


def _service(index: _RecordingIndex) -> TutorService:
    return TutorService(index=index, provider=_Stub(), term_stats=None)


# ------------------------------------------------------------ multi-turn ---
def test_short_followup_retrieves_with_prior_turn_context() -> None:
    index = _RecordingIndex()
    service = _service(index)
    history = [
        {"role": "user", "content": "ভগ্নাংশ কী?"},
        {"role": "assistant", "content": "ভগ্নাংশ হলো..."},
    ]
    augmented = service._conversation_retrieval_query("এটা আবার", history)
    assert "ভগ্নাংশ" in augmented
    assert augmented.startswith("এটা আবার")


def test_rich_followup_is_never_rewritten() -> None:
    service = _service(_RecordingIndex())
    question = "সালোকসংশ্লেষণ কী এবং কোথায় ঘটে?"
    history = [{"role": "user", "content": "ভগ্নাংশ কী?"}]
    assert service._conversation_retrieval_query(question, history) == question


@pytest.mark.asyncio
async def test_search_query_override_passes_through_untouched() -> None:
    # The override is a deliberate routing decision (quiz-explain); rewriting
    # it would break retrieval for the exact item the teacher pointed at.
    # Asserted end-to-end: the override must reach the index verbatim, not
    # merged with the prior turn's terms.
    index = _RecordingIndex()
    service = _service(index)
    await service.ask(
        "এটা আবার",
        8,
        history=[{"role": "user", "content": "ভগ্নাংশ কী?"}],
        search_query="সংজ্ঞা",
    )
    assert index.queries == ["সংজ্ঞা"]


def test_empty_history_or_empty_context_never_rewrites() -> None:
    service = _service(_RecordingIndex())
    question = "এটা আবার"
    assert service._conversation_retrieval_query(question, None) == question
    # prior turn has no content terms (only stop/function words)
    assert (
        service._conversation_retrieval_query(question, [{"role": "user", "content": "কেন?"}])
        == question
    )


# ------------------------------------------------------ event-loop freedom ---
@pytest.mark.asyncio
async def test_concurrent_asks_do_not_serialize_on_the_event_loop() -> None:
    delay = 0.3
    index = _RecordingIndex(search_delay=delay)
    service = _service(index)

    started = time.perf_counter()
    await asyncio.gather(
        service.ask("ভগ্নাংশ কী?", 8),
        service.ask("কোষ কী?", 8),
    )
    elapsed = time.perf_counter() - started
    # Serial execution would cost >= 2*delay (plus overhead); offloaded
    # execution costs ~max(delay) + thread-pool overhead. The margin keeps
    # the assertion stable on a loaded CI runner while still failing the
    # moment retrieval runs back on the event loop.
    assert elapsed < delay * 1.8, f"retrieval serialized on the loop: {elapsed:.2f}s"
    assert len(index.queries) == 2


# --------------------------------------------------------- observability ---
@pytest.mark.asyncio
async def test_gate_metrics_record_refused_turn() -> None:
    index = _RecordingIndex()
    service = _service(index)

    before_outcome = _counter_value("bgpt_rag_gate_outcomes_total", {"gate": "refuse"}) or 0.0
    before_refusal = (
        _counter_value("bgpt_rag_gate_refusals_total", {"reason": "insufficient_evidence"}) or 0.0
    )
    before_latency = _counter_value("bgpt_rag_retrieval_latency_seconds_count") or 0.0

    response = await service.ask("ভগ্নাংশ কী?", 8)

    assert response.grounded is False
    assert response.refused_reason == "insufficient_evidence"
    assert (_counter_value("bgpt_rag_gate_outcomes_total", {"gate": "refuse"}) or 0.0) == (
        before_outcome + 1.0
    )
    assert (
        _counter_value("bgpt_rag_gate_refusals_total", {"reason": "insufficient_evidence"}) or 0.0
    ) == (before_refusal + 1.0)
    assert (_counter_value("bgpt_rag_retrieval_latency_seconds_count") or 0.0) == (
        before_latency + 1.0
    )


@pytest.mark.asyncio
async def test_safety_refusal_reason_is_metered_before_retrieval() -> None:
    index = _RecordingIndex()
    service = _service(index)

    before = _counter_value("bgpt_rag_gate_refusals_total", {"reason": "self_harm"}) or 0.0
    response = await service.ask("আত্মহত্যা করার উপায় কী?", 8)

    assert response.refused_reason == "self_harm"
    # The screen runs pre-retrieval: no query may have reached a poisoned index.
    assert index.queries == []
    assert (_counter_value("bgpt_rag_gate_refusals_total", {"reason": "self_harm"}) or 0.0) == (
        before + 1.0
    )


@pytest.mark.asyncio
async def test_citation_check_enforced_and_warned_on_fail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AUD-A2-03: a failed citation check replaces the answer (never shown)."""
    from bangla_gpt_api.services.tutor import INSUFFICIENT_EVIDENCE_ANSWER

    service = _service(_RecordingIndex())

    before_fail = _counter_value("bgpt_rag_citation_checks_total", {"result": "fail"}) or 0.0
    before_pass = _counter_value("bgpt_rag_citation_checks_total", {"result": "pass"}) or 0.0
    before_enforced = (
        _counter_value("bgpt_rag_gate_refusals_total", {"reason": "citation_unverified"}) or 0.0
    )

    with caplog.at_level("WARNING", logger="bangla_gpt_api.tutor"):
        response = service._assemble(
            "সম্পূর্ণ অসম্পর্কিত উত্তর",
            hits=[],
            question="কোষ কী?",
            route="simple",
            provider=_Stub(),
            context_blocks="blocks",
            started=0.0,
        )
    assert response.grounded is False
    assert response.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert response.refused_reason == "citation_unverified"
    assert response.sources == []
    assert response.citation_verified is None
    assert (_counter_value("bgpt_rag_citation_checks_total", {"result": "fail"}) or 0.0) == (
        before_fail + 1.0
    )
    assert (
        _counter_value("bgpt_rag_citation_checks_total", {"result": "pass"}) or 0.0
    ) == before_pass
    assert (
        _counter_value("bgpt_rag_gate_refusals_total", {"reason": "citation_unverified"}) or 0.0
    ) == (before_enforced + 1.0)
    assert any("citation_check_failed" in r.message for r in caplog.records)


def test_model_refusal_is_refusal_metered_without_citation_check() -> None:
    service = _service(_RecordingIndex())

    before_refusal = (
        _counter_value("bgpt_rag_gate_refusals_total", {"reason": "model_refused"}) or 0.0
    )
    pass_total = _counter_value("bgpt_rag_citation_checks_total", {"result": "pass"}) or 0.0
    fail_total = _counter_value("bgpt_rag_citation_checks_total", {"result": "fail"}) or 0.0

    response = service._assemble(
        "এটি পাঠ্যবইয়ে নেই",
        hits=[],
        question="কোষ কী?",
        route="simple",
        provider=_Stub(),
        context_blocks="blocks",
        started=0.0,
    )
    assert response.refused_reason == "model_refused"
    assert response.citation_verified is None
    assert (_counter_value("bgpt_rag_gate_refusals_total", {"reason": "model_refused"}) or 0.0) == (
        before_refusal + 1.0
    )
    # A refusal is not a citation event: neither verdict may tick.
    assert (
        _counter_value("bgpt_rag_citation_checks_total", {"result": "fail"}) or 0.0
    ) == fail_total
    assert (
        _counter_value("bgpt_rag_citation_checks_total", {"result": "pass"}) or 0.0
    ) == pass_total


# --------------------------------------------------------- stream parity ---
@pytest.mark.asyncio
async def test_stream_gate_refusal_matches_non_stream_contract() -> None:
    index = _RecordingIndex()
    service = _service(index)

    before_refusal = (
        _counter_value("bgpt_rag_gate_refusals_total", {"reason": "insufficient_evidence"}) or 0.0
    )
    events = [event async for event in service.ask_stream("ভগ্নাংশ কী?", 8)]

    final = events[-1]
    assert final.type == "final"
    assert final.response is not None
    assert final.response.grounded is False
    assert final.response.refused_reason == "insufficient_evidence"
    # Parity with the non-stream path: "not applicable" is None, not False.
    assert final.response.citation_verified is None
    assert (
        _counter_value("bgpt_rag_gate_refusals_total", {"reason": "insufficient_evidence"}) or 0.0
    ) == (before_refusal + 1.0)
