# Tracing — per-stage records today, OpenTelemetry when a collector exists

> Audience: operators and the next engineer who picks up observability. This
> document states exactly what is implemented, what is not, and why.

## What ships today (AUD-HI-04 / I-03)

Set `TRACING_ENABLED=true` and the API emits **one structured JSON record per
pipeline stage** on the existing log sink:

```json
{"event": "trace", "stage": "retrieval", "trace_id": "…",
 "retrieval_ms": 41, "evidence_chunks": 3, "top_score": 0.72,
 "coverage": 0.91, "gate": "pass",
 "index_version": "HybridIndex:2504:9f2c…", "stream": false,
 "retrieved_ids": ["nctb-…-0042", "…"], "request_id": "…"}
{"event": "trace", "stage": "generation", "trace_id": "…",
 "route": "rag", "model": "gemini-3.1-flash-lite",
 "prompt_version": "sp-6b1f…", "index_version": "HybridIndex:2504:9f2c…",
 "prompt_tokens": 812, "completion_tokens": 190, "answer_chars": 640,
 "latency_ms": 1840, "request_id": "…"}
```

Guarantees this gives an incident responder, without a collector:

| Question | Answer source |
|---|---|
| Which corpus produced this answer? | `index_version` (class, chunk count, sha256 of the chunk-id set — derived at boot, not maintained by hand) |
| Which prompt text? | `prompt_version` (**sha256 of the system prompt in this build** — a prompt edit cannot leave a stale version) |
| Which chunks were retrieved, and how did the gate vote? | `retrieved_ids`, `gate`, `coverage`, `top_score` |
| What did it cost? | `prompt_tokens` / `completion_tokens`, from the same estimator as the ledger |
| How do I join the stages of one ask? | `trace_id` — set to the request id by `RequestIdMiddleware`, so it matches `X-Request-ID`, the access log line and any 500 body |

Implementation: `logging_config.trace_event` (behind the flag),
`middleware.RequestIdMiddleware` (trace-id seed),
`services/tutor.py` (`_trace_retrieval`, `_trace_generation`).

Privacy: student question text is never a field on a trace record. The
service's logging posture is that wording is PII-adjacent; these records carry
counts, ids and versions only.

## What does NOT ship (deferred, with the reason)

Full OpenTelemetry — SDK, auto-instrumentation for FastAPI/SQLAlchemy/httpx,
OTLP export and a collector — is **deferred**:

1. There is no collector endpoint in any environment in this repository, so
   the SDK would add a dependency and per-request overhead to export into
   nothing.
2. The `otel` packages are not in the dependency lock; adding them changes the
   supply-chain surface and needs the owner's Dependabot/audit attention
   (T6).
3. The gate's own wording accepts an equivalent: correlated per-stage records
   with the request id, versions, token counts and retrieved ids. That is what
   ships above, behind a flag, with a test.

**Upgrade path** (when the owner stands up a collector):

1. Add `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`,
   `-sqlalchemy`, `-httpx` to `apps/api/pyproject.toml` (locked, audited).
2. Replace the body of `logging_config.trace_event` with a span emission,
   keeping the same field names — every call site stays untouched.
3. Point `OTEL_EXPORTER_OTLP_ENDPOINT` at the collector; keep `TRACING_ENABLED`
   as the sampling switch until a sampling policy is agreed.

## Operator quickstart

```bash
TRACING_ENABLED=true uvicorn …            # or set it in .env for a staging soak
# one ask, then:
grep '"event": "trace"' api.log | grep '"stage": "retrieval"'
```

Trace records are per-request at INFO level; a busy staging environment
produces two lines per tutoring turn. Keep the flag **off** in production
until the log pipeline has a retention policy for them (they are not PII, but
they are volume).
