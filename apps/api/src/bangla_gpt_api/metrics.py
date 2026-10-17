"""Prometheus metrics for the API service.

Counters/histograms are registered once per process on a dedicated registry
so multiple ``create_app`` instances (tests, workers) never double-register.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

REQUESTS_TOTAL = Counter(
    "bgpt_http_requests_total",
    "Total HTTP requests processed.",
    labelnames=["method", "path", "status"],
    registry=REGISTRY,
)

REQUEST_LATENCY_SECONDS = Histogram(
    "bgpt_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=["path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

UNHANDLED_EXCEPTIONS_TOTAL = Counter(
    "bgpt_http_unhandled_exceptions_total",
    "Unhandled exceptions escaping the application.",
    labelnames=["method", "path"],
    registry=REGISTRY,
)

PII_REDACTED_TOTAL = Counter(
    "bgpt_pii_redacted_total",
    "PII spans stripped by the pre-LLM redactor before upstream egress.",
    labelnames=["kind"],
    registry=REGISTRY,
)

# Boot-level retrieval state: which corpus the tutor is actually serving and
# how large it is. The operational failure this answers is silent degradation
# -- an empty or mis-set NCTB_CORPUS_DIR dropping the tutor onto the bundled
# sample corpus -- which used to be invisible in metrics, logs and answers
# alike until a student asked a question the sample does not contain.
RAG_INDEX_CHUNKS = Gauge(
    "bgpt_rag_index_chunks",
    "Chunks loaded into the retrieval index at boot, by corpus identity (nctb or bundled-sample).",
    labelnames=["corpus"],
    registry=REGISTRY,
)

# RAG hot-path latency. The tutor's retrieval+rerank stage is CPU-bound;
# this histogram is the p50/p95 signal for scaling decisions (index size vs
# latency) that previously lived only in one-off eval scripts.
RAG_RETRIEVAL_LATENCY_SECONDS = Histogram(
    "bgpt_rag_retrieval_latency_seconds",
    "Retrieval + rerank latency per tutoring turn (index search only, gate excluded).",
    buckets=(0.005, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)

# Grounding-gate verdicts: one per tutoring turn. Aggregate volume backs the
# HighRAGRefusalRate alert (denominator); a refuse-heavy shift is the
# signature of silent corpus degradation or a retrieval regression.
RAG_GATE_OUTCOMES_TOTAL = Counter(
    "bgpt_rag_gate_outcomes_total",
    "Grounding-gate verdicts per tutoring turn (pass or refuse).",
    labelnames=["gate"],
    registry=REGISTRY,
)

# Refusal reasons, including the safety screen (which runs before retrieval):
# each blocked category is low-rate, high-signal traffic worth one label --
# more precise than folding them into the aggregate outcome series alone.
RAG_GATE_REFUSALS_TOTAL = Counter(
    "bgpt_rag_gate_refusals_total",
    "Tutor refusals by reason (safety categories, insufficient_evidence, model_refused).",
    labelnames=["reason"],
    registry=REGISTRY,
)

# Post-generation citation verification. A fail means the grounded answer
# leaned on material the evidence does not support -- previously a boolean
# dropped into the response with no metering, so ungrounded drift in
# production (new provider, new corpus) was invisible.
RAG_CITATION_CHECKS_TOTAL = Counter(
    "bgpt_rag_citation_checks_total",
    "Post-generation citation verification verdicts on grounded answers.",
    labelnames=["result"],
    registry=REGISTRY,
)
