"""Answer observability: per-answer traces and per-stage latency (RAG-26/29).

Two gaps this module closes, both in the RAG stream:

* **No per-answer trace.** Logs carried a request id and aggregate counts, so
  after a bad answer nobody could say which chunks were retrieved, which
  prompt hash produced it, which model and parameters answered, or how the
  citation check judged it. :class:`AnswerTrace` records exactly that, and
  deliberately nothing else: the question is stored as a SHA-256 fingerprint,
  the retrieved chunks as ids and scores, and no student text of any kind.
* **No per-stage latency.** Only the retrieval stage was measured, so rewrite,
  gate, generation and time-to-first-token were invisible and p99 could not be
  quoted. The histograms below are labelled by stage only -- no user id, no
  question, no model -- so cardinality is bounded by the stage set.

Retention: the trace ring is in-process and bounded (:data:`TRACE_CAPACITY`);
traces are diagnostics for the last few hundred answers, not a record of a
child's work, and nothing here is written to the database. The aggregate is
what a board should read (counts, rates, percentiles) -- the individual
traces are for the operator investigating a specific complaint.
"""

from __future__ import annotations

import hashlib
import threading
import time
import unicodedata
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from prometheus_client import Counter, Histogram

from bangla_gpt_api.evaluation.stats import percentile
from bangla_gpt_api.metrics import REGISTRY

#: Ring size for the in-process trace store. Small on purpose: a trace answers
#: "what happened to this answer" during an investigation, and a bounded deque
#: cannot become a shadow copy of a child's conversation history.
TRACE_CAPACITY = 500

#: Per-stage latency, seconds. The stage label set is fixed (see
#: :data:`STAGES`), which keeps the series count constant no matter how much
#: traffic arrives; no user, question or model label exists anywhere here.
STAGES = ("rewrite", "retrieval", "gate", "generate", "ttft", "total")

RAG_STAGE_LATENCY_SECONDS = Histogram(
    "bgpt_rag_stage_latency_seconds",
    "Per-stage answer latency in seconds, by stage (rewrite, retrieval, gate, generate, ttft, total).",
    labelnames=["stage"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    registry=REGISTRY,
)

#: Answer outcomes, one label per trace. "answered" is the grounded path; the
#: other three mirror the refusal reasons the response carries.
OUTCOMES = ("answered", "safety_refusal", "insufficient_evidence", "model_refused", "outage")

#: Retrieval degradation events (RAG-28). ``lexical_fallback`` means the hybrid
#: lane raised and the lexical lane served the turn; ``unavailable`` means no
#: lane could, so the gate refuses. Both are bounded label values; a rising
#: fallback rate is the signal that the hybrid pipeline is failing.
RAG_RETRIEVAL_DEGRADED_TOTAL = Counter(
    "bgpt_rag_retrieval_degraded_total",
    "Retrieval turns served by the fallback lane or refused because no lane served them.",
    labelnames=["stage"],
    registry=REGISTRY,
)

#: Generation admission (F-117/LLM-11): turns refused because the per-process
#: concurrency cap stayed saturated past the queue timeout. This is the metric
#: an operator needs before raising the cap or the worker count.
RAG_GENERATION_OVERLOAD_TOTAL = Counter(
    "bgpt_generation_overload_total",
    "Generation turns refused at the concurrency cap (bounded admission).",
    labelnames=["stage"],
    registry=REGISTRY,
)


def observe_stage(stage: str, seconds: float) -> None:
    """Record one stage observation (unknown stages are ignored, not invented)."""
    if stage in STAGES:
        RAG_STAGE_LATENCY_SECONDS.labels(stage=stage).observe(max(0.0, seconds))


def query_fingerprint(text: str, *, length: int = 16) -> str:
    """Stable privacy-safe fingerprint of a question.

    NFKC + whitespace squash before hashing so the same typed question with a
    different keyboard form fingerprints identically, and the digest is
    truncated: it groups repeated questions for triage and cannot be used to
    enumerate them (the space of Bangla sentences is far larger than 2**64).
    """
    normalised = unicodedata.normalize("NFKC", text or "")
    squashed = " ".join(normalised.split())
    return hashlib.sha256(squashed.encode("utf-8")).hexdigest()[:length]


@dataclass
class AnswerTrace:
    """One privacy-safe answer record (see the module docstring)."""

    trace_version: str
    recorded_at: float
    query_sha256: str
    prompt_sha256: str
    prompt_version: str
    outcome: str
    grounded: bool
    refused_reason: str | None
    rewrite_applied: bool
    rewrite_terms: int
    #: Fingerprint of the composed prompt actually sent (chunks + history +
    #: question). The template hash above identifies the revision; this one
    #: identifies the exact bytes, which is what reproducing an answer needs.
    composed_prompt_sha256: str | None = None
    chunk_ids: list[str] = field(default_factory=list)
    chunk_scores: list[float] = field(default_factory=list)
    model: str = "unknown"
    parameters: dict[str, Any] = field(default_factory=dict)
    citation_verdict: str | None = None
    latency_ms: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


class AnswerTraceStore:
    """Thread-safe bounded ring of traces plus the aggregate a board reads."""

    def __init__(self, capacity: int = TRACE_CAPACITY) -> None:
        self._capacity = max(1, capacity)
        self._traces: deque[AnswerTrace] = deque(maxlen=self._capacity)
        self._lock = threading.Lock()
        self._total = 0

    def record(self, trace: AnswerTrace) -> None:
        with self._lock:
            self._traces.append(trace)
            self._total += 1

    def recent(self, limit: int = 50) -> list[AnswerTrace]:
        with self._lock:
            items = list(self._traces)
        return items[-max(0, limit) :]

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()
            self._total = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    def aggregate(self) -> dict:
        """Counts, rates and latency percentiles over the retained window.

        This is the payload a dashboard reads: nothing per-answer leaves the
        process, so a board cannot display a child's question even by mistake.
        """
        with self._lock:
            traces = list(self._traces)
            total_recorded = self._total
        if not traces:
            return {
                "trace_version": TRACE_VERSION,
                "retained": 0,
                "capacity": self._capacity,
                "total_recorded": total_recorded,
            }
        by_outcome: dict[str, int] = {}
        citation: dict[str, int] = {}
        latencies: dict[str, list[float]] = {
            stage: [] for stage in ("total", "retrieval", "generate", "ttft")
        }
        models: dict[str, int] = {}
        for trace in traces:
            by_outcome[trace.outcome] = by_outcome.get(trace.outcome, 0) + 1
            verdict = trace.citation_verdict or "not_applicable"
            citation[verdict] = citation.get(verdict, 0) + 1
            models[trace.model] = models.get(trace.model, 0) + 1
            for stage in latencies:
                value = trace.latency_ms.get(stage)
                if value is not None:
                    latencies[stage].append(float(value))
        retained = len(traces)
        grounded = sum(1 for trace in traces if trace.grounded)
        return {
            "trace_version": TRACE_VERSION,
            "retained": retained,
            "capacity": self._capacity,
            "total_recorded": total_recorded,
            "grounded_rate": round(grounded / retained, 4),
            "refusal_rate": round(1 - grounded / retained, 4),
            "by_outcome": dict(sorted(by_outcome.items())),
            "by_model": dict(sorted(models.items())),
            "citation_verdicts": dict(sorted(citation.items())),
            "latency_ms": {
                stage: {
                    "n": len(values),
                    "p50": round(percentile(values, 50), 1),
                    "p95": round(percentile(values, 95), 1),
                    "p99": round(percentile(values, 99), 1),
                }
                for stage, values in latencies.items()
                if values
            },
            "prompt_versions": sorted({trace.prompt_version for trace in traces}),
            "window_recorded_at": [traces[0].recorded_at, traces[-1].recorded_at],
        }


#: Version of the trace schema. A field change is a version bump so a consumer
#: (log parser, dashboard) can tell which shape it is reading.
TRACE_VERSION = "answer-trace-v1"

#: Default store the tutor writes to. Tests build their own store and pass it
#: to :class:`~bangla_gpt_api.services.tutor.TutorService` instead.
TRACE_STORE = AnswerTraceStore()


def record_trace(*, store: AnswerTraceStore | None = None, **fields: Any) -> AnswerTrace:
    """Build and record a trace; returns it so tests can assert on the record."""
    trace = AnswerTrace(recorded_at=time.time(), **fields)
    (store or TRACE_STORE).record(trace)
    for stage, value in trace.latency_ms.items():
        observe_stage(stage, value / 1000.0)
    return trace
