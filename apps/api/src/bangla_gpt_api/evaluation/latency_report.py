"""Per-stage latency measurement for the RAG answer path (RAG-26).

Measurements, not a service: this script runs the hermetic stack (mock
provider, bundled sample corpus, hybrid index) over the committed golden set
and reports p50/p95/p99 for every stage the answer path has:

* ``rewrite``, ``gate``, ``generate``, ``total`` and ``ttft`` come from the
  per-answer traces the tutor records (RAG-29), so the numbers are the ones a
  running worker produces, not a re-implementation;
* ``retrieval`` is the index search the tutor performs (BM25 + vector + RRF +
  rerank);
* ``lexical_lane``, ``vector_lane`` and ``rerank`` decompose that search. The
  reranker and the lane objects are wrapped in place, so the decomposition
  measures the real pipeline rather than a copy of it that can drift.

Usage (through the eval CLI, which owns all console output)::

    cd apps/api
    python -m bangla_gpt_api.evaluation.cli --latency-report
    python -m bangla_gpt_api.evaluation.cli --latency-report --latency-items 0

The corpus size is reported with the numbers because latency is meaningless
without it: the index is in-memory and per worker, so the same code is much
faster on the bundled sample corpus (78 chunks) than on the full NCTB corpus.
"""

from __future__ import annotations

import platform
import time
from typing import Any

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation.observability import AnswerTraceStore
from bangla_gpt_api.evaluation.stats import percentile_report

#: Stage names the report prints, in pipeline order.
STAGES = (
    "rewrite",
    "retrieval",
    "lexical_lane",
    "vector_lane",
    "rerank",
    "gate",
    "ttft",
    "generate",
    "total",
)


def _time_call(owner: Any, attribute: str, sink: list[float]) -> None:
    """Time one callable attribute in place (harness-only; the wrapped object
    is discarded when the process exits, so no production path sees this)."""
    original = getattr(owner, attribute)

    def timed(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            sink.append((time.perf_counter() - started) * 1000.0)

    setattr(owner, attribute, timed)


def _build_stack() -> tuple[Any, Any, list[dict], Settings]:
    from bangla_gpt_api.evaluation.golden_v3 import build_items
    from bangla_gpt_api.providers.mock import MockLLMProvider
    from bangla_gpt_api.retrieval.embedding import build_embedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
    from bangla_gpt_api.services.tutor import TutorService

    settings = Settings(env="test", llm_provider="mock")
    chunks = load_sample_corpus()
    index = HybridIndex(chunks, build_embedder(settings))
    tutor = TutorService(index=index, provider=MockLLMProvider(), term_stats=index.term_stats)
    return tutor, index, build_items(chunks), settings


async def measure(*, items_limit: int = 120, stream_samples: int = 40) -> dict:
    """Run the hermetic stack and return the per-stage latency report."""
    tutor, index, items, _settings = _build_stack()
    positives = [item for item in items if item["expect"] == "answer"]
    if items_limit:
        positives = positives[:items_limit]
    samples = min(stream_samples, len(positives)) if stream_samples else len(positives)

    # --- stage traces through the real tutor (ask + stream) -------------------
    store = AnswerTraceStore(capacity=10_000)
    tutor.trace_store = store
    for item in positives:
        await tutor.ask(item["question"], item["class_level"], item.get("subject"))
    for item in positives[:samples]:
        async for _event in tutor.ask_stream(
            item["question"], item["class_level"], item.get("subject")
        ):
            pass

    trace_stages: dict[str, list[float]] = {}
    for trace in store.recent(store.capacity):
        for stage, value in trace.latency_ms.items():
            trace_stages.setdefault(stage, []).append(float(value))

    # --- lane and reranker decomposition of the search stage -----------------
    lexical_ms: list[float] = []
    vector_ms: list[float] = []
    rerank_ms: list[float] = []
    _time_call(index.bm25, "search", lexical_ms)
    _time_call(index.vector, "search", vector_ms)
    _time_call(index, "reranker", rerank_ms)
    search_ms: list[float] = []
    for item in positives:
        started = time.perf_counter()
        index.search(
            item["question"],
            class_level=item["class_level"],
            subject=item.get("subject"),
            top_k=tutor.top_k,
        )
        search_ms.append((time.perf_counter() - started) * 1000.0)

    per_stage = {
        "rewrite": percentile_report(trace_stages.get("rewrite", [])),
        "retrieval": percentile_report(trace_stages.get("retrieval", [])),
        "gate": percentile_report(trace_stages.get("gate", [])),
        "ttft": percentile_report(trace_stages.get("ttft", [])),
        "generate": percentile_report(trace_stages.get("generate", [])),
        "total": percentile_report(trace_stages.get("total", [])),
        "lexical_lane": percentile_report(lexical_ms),
        "vector_lane": percentile_report(vector_ms),
        "rerank": percentile_report(rerank_ms),
        "hybrid_search": percentile_report(search_ms),
    }
    return {
        "measured_by": "bangla_gpt_api.evaluation.latency_report",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "corpus": {"chunks": len(load_sample_corpus()), "identity": "bundled-sample"},
        "provider": "mock",
        "items_measured": len(positives),
        "stream_samples": samples,
        "unit": "milliseconds",
        "stages": per_stage,
        "note": (
            "retrieval is the search the tutor performs (lexical + vector + RRF + rerank);"
            " hybrid_search is the same call measured again without the tutor's thread"
            " offload; lexical_lane/vector_lane/rerank decompose it; ttft is the"
            " streaming path only"
        ),
    }


#: Print order for :func:`format_table` (pipeline order).
TABLE_STAGES = (
    "rewrite",
    "retrieval",
    "lexical_lane",
    "vector_lane",
    "rerank",
    "gate",
    "ttft",
    "generate",
    "total",
)


def format_table(report: dict) -> str:
    """Human-readable rendering of :func:`measure`'s report."""
    lines = [
        f"corpus: {report['corpus']['chunks']} chunks ({report['corpus']['identity']}), "
        f"provider={report['provider']}, items={report['items_measured']}, "
        f"stream_samples={report['stream_samples']}",
        "stage               n      p50      p95      p99   (ms)",
    ]
    for stage in TABLE_STAGES:
        values = report["stages"].get(stage)
        if not values or not values["n"]:
            continue
        lines.append(
            f"{stage:14s} {values['n']:6d} {values['p50']:8.1f} {values['p95']:8.1f} "
            f"{values['p99']:8.1f}"
        )
    return "\n".join(lines)
