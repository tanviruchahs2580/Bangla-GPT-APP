"""Per-answer traces and prompt identity (RAG-13, RAG-26, RAG-29).

The defect these tests pin: an answer could not be attributed to a prompt
revision, and nothing recorded which chunks, model, parameters or citation
verdict produced it. The trace must carry that evidence while carrying no
student text of any kind -- the privacy half is asserted, not assumed.
"""

from __future__ import annotations

import asyncio
import json

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation.observability import (
    TRACE_VERSION,
    AnswerTraceStore,
    query_fingerprint,
)
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import PROMPT_SHA256, PROMPT_VERSION, TutorService, prompt_sha256

_QUESTION = "কোষ কী?"


def _tutor(store: AnswerTraceStore) -> TutorService:
    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    return TutorService(
        index=index,
        provider=MockLLMProvider(),
        term_stats=index.term_stats,
        trace_store=store,
    )


def test_query_fingerprint_is_stable_and_text_free() -> None:
    fingerprint = query_fingerprint(_QUESTION)
    assert fingerprint == query_fingerprint("  " + _QUESTION + "  ")
    assert fingerprint != query_fingerprint("কোষ কী")
    assert _QUESTION not in fingerprint
    assert len(fingerprint) == 16


def test_answered_turn_records_a_complete_trace() -> None:
    store = AnswerTraceStore(capacity=4)
    tutor = _tutor(store)
    response = asyncio.run(tutor.ask(_QUESTION, 6, "science"))
    assert response.grounded is True
    traces = store.recent(1)
    assert len(traces) == 1
    trace = traces[0]
    assert trace.trace_version == TRACE_VERSION
    assert trace.outcome == "answered"
    assert trace.grounded is True
    assert trace.query_sha256 == query_fingerprint(_QUESTION)
    assert trace.prompt_sha256 == PROMPT_SHA256
    assert trace.prompt_version == PROMPT_VERSION
    assert trace.chunk_ids and len(trace.chunk_ids) == len(trace.chunk_scores)
    assert trace.citation_verdict in {"verified", "unverified:no_evidence"}
    assert trace.model == "mock"
    assert trace.parameters["top_k"] == tutor.top_k
    for stage in ("rewrite", "retrieval", "gate", "generate", "total"):
        assert trace.latency_ms[stage] >= 0


def test_trace_carries_no_student_text() -> None:
    store = AnswerTraceStore(capacity=4)
    tutor = _tutor(store)
    asyncio.run(tutor.ask(_QUESTION, 6, "science"))
    serialised = json.dumps(store.recent(1)[0].as_dict(), ensure_ascii=False)
    assert _QUESTION not in serialised
    assert "কোষ" not in serialised


def test_refusal_paths_are_traced_with_their_reason() -> None:
    store = AnswerTraceStore(capacity=8)
    tutor = _tutor(store)
    gate_refusal = asyncio.run(tutor.ask("মঙ্গল গ্রহে প্রাণ আছে?", 6, "science"))
    assert gate_refusal.grounded is False
    safety_refusal = asyncio.run(tutor.ask("আমি মরে যেতে চাই", 6, "science"))
    assert safety_refusal.grounded is False
    outcomes = [trace.outcome for trace in store.recent(8)]
    assert "insufficient_evidence" in outcomes
    assert "safety_refusal" in outcomes


def test_store_is_bounded_and_aggregates_the_window() -> None:
    store = AnswerTraceStore(capacity=2)
    tutor = _tutor(store)
    for _ in range(3):
        asyncio.run(tutor.ask(_QUESTION, 6, "science"))
    assert len(store.recent(10)) == 2
    aggregate = store.aggregate()
    assert aggregate["retained"] == 2
    assert aggregate["total_recorded"] == 3
    assert aggregate["capacity"] == 2
    assert aggregate["grounded_rate"] == 1.0
    assert aggregate["refusal_rate"] == 0.0
    assert aggregate["by_model"] == {"mock": 2}
    assert aggregate["citation_verdicts"]
    assert set(aggregate["latency_ms"]) >= {"total", "retrieval", "generate"}
    assert aggregate["latency_ms"]["total"]["p95"] >= 0
    assert PROMPT_VERSION in aggregate["prompt_versions"]


def test_empty_store_aggregate_is_honest() -> None:
    aggregate = AnswerTraceStore(capacity=5).aggregate()
    assert aggregate["retained"] == 0
    assert aggregate["capacity"] == 5
    assert "grounded_rate" not in aggregate


def test_streaming_turn_records_ttft() -> None:
    store = AnswerTraceStore(capacity=4)
    tutor = _tutor(store)

    async def consume() -> None:
        async for _event in tutor.ask_stream(_QUESTION, 6, "science"):
            pass

    asyncio.run(consume())
    trace = store.recent(1)[0]
    assert trace.parameters["stream"] is True
    assert "ttft" in trace.latency_ms


def test_prompt_hash_follows_the_prompt_text() -> None:
    assert prompt_sha256() == PROMPT_SHA256
    assert prompt_sha256("different instructions") != PROMPT_SHA256
    assert len(PROMPT_SHA256) == 64
    assert PROMPT_VERSION.startswith("tutor-prompt-")
