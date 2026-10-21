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

# Boot-time index construction. The index is rebuilt in-memory per worker at
# start (the accepted design at this corpus scale), so build duration is the
# signal that says when the deferred pgvector/persistence work becomes
# necessary, and it makes a slow boot attributable during a rolling deploy.
RAG_INDEX_BUILD_SECONDS = Histogram(
    "bgpt_rag_index_build_seconds",
    "Wall time to build the retrieval index at process boot.",
    labelnames=["mode"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
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

# --------------------------------------------------------------------------
# Business signals (AUD-HI-03 / I-02). The RAG counters above answer "is the
# pipeline healthy"; these answer "is the product being used and is it
# refusing more than it used to". Both were previously derivable only by
# querying the ai_usage table, so no dashboard or alert could see them.
# --------------------------------------------------------------------------

#: One increment per completed tutoring turn. ``outcome`` is a fixed
#: vocabulary so `refused / total` is a stable, dashbordable refusal rate
#: (the per-reason split stays on bgpt_rag_gate_refusals_total).
AI_ANSWERS_TOTAL = Counter(
    "bgpt_ai_answers_total",
    "Tutor answers by route and outcome (answered or refused); refusal rate = refused / total.",
    labelnames=["route", "outcome"],
    registry=REGISTRY,
)

#: Estimated tokens by direction, from the same estimator the cost ledger
#: uses (services/costs.py). Labelled by model so a provider switch is
#: visible in the token mix before it shows up on the invoice.
AI_TOKENS_TOTAL = Counter(
    "bgpt_ai_tokens_total",
    "Estimated LLM tokens (planning estimate, see services/costs.py) by model and direction.",
    labelnames=["model", "direction"],
    registry=REGISTRY,
)

#: Estimated spend in USD, list-price based. The monthly-budget burn alert in
#: deploy/prometheus/alerts.yml and the cost dashboard panel both read this.
AI_COST_USD_TOTAL = Counter(
    "bgpt_ai_cost_usd_total",
    "Estimated LLM spend in USD (list-price estimate, see services/costs.py) by model and route.",
    labelnames=["model", "route"],
    registry=REGISTRY,
)

#: The operator-configured global monthly AI budget (0 = not configured).
#: Exported as a gauge rather than created on demand because an alert rule
#: cannot reference a series that may not exist; the burn-rate rule in
#: deploy/prometheus/alerts.yml therefore gates on ``> 0``, so an unset
#: budget can never produce a false page.
AI_MONTHLY_BUDGET_USD = Gauge(
    "bgpt_ai_monthly_budget_usd",
    "Operator-configured global monthly AI budget in USD (0 = not configured).",
    registry=REGISTRY,
)

#: Async job outcomes (teacher Create hub). ``kind`` is the document kind,
#: ``status`` is the terminal status (ready or failed) -- a rising failed
#: share is the signal that generation quality or the provider is degrading.
AI_JOBS_TOTAL = Counter(
    "bgpt_ai_jobs_total",
    "Async AI generation jobs by kind and terminal status (ready or failed).",
    labelnames=["kind", "status"],
    registry=REGISTRY,
)


def set_ai_budget_usd(budget_usd: float) -> None:
    """Publish the configured global monthly AI budget (0 = not configured).

    Called once per app build. The gauge is what makes the burn-rate alert in
    ``deploy/prometheus/alerts.yml`` meaningful without hard-coding a dollar
    figure in the rule file; the rule gates on ``> 0``, so the unset default
    cannot fire.
    """
    AI_MONTHLY_BUDGET_USD.set(float(budget_usd) if budget_usd and budget_usd > 0 else 0.0)


#: The bounded route vocabulary for bgpt_ai_answers_total. Anything else is
#: folded into "other" (defence against label-cardinality growth).
TUTOR_ROUTES = frozenset({"tutor", "tutor.chat", "tutor.chat.stream", "quiz_explain"})


def record_tutor_answer(route: str, outcome: str) -> None:
    """Count one finished tutoring turn (outcome: ``answered`` | ``refused``).

    Bounded label values only -- an unexpected value is folded into
    ``other`` so a future call site cannot inflate the series count.
    """
    safe_outcome = outcome if outcome in ("answered", "refused") else "other"
    safe_route = route if route in TUTOR_ROUTES else "other"
    AI_ANSWERS_TOTAL.labels(route=safe_route, outcome=safe_outcome).inc()
