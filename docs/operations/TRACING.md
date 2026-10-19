# Tracing — OpenTelemetry spans plus per-stage trace records (I-03)

> Audience: operators and the next engineer who picks up observability. This
> document states exactly what is implemented, how to switch it on, and what
> is deliberately not collected.

## What ships today

Two layers, both fed by the same call sites:

1. **Per-stage trace records** — one structured JSON line per pipeline stage
   on the log sink (always available, no collector needed). This is the layer
   a `grep` uses during an incident.
2. **OpenTelemetry spans** — the distributed-tracing layer: server spans, DB
   statement spans, an LLM-call span and a job-worker span, joined into one
   trace per request and exportable over OTLP.

### Span inventory

| Span | Created by | Attributes (no PII) |
|---|---|---|
| `POST /tutor/ask` (and every other route) | `instrumentation-fastapi` via `tracing.instrument_app` | `http.request.method`, `http.route`, `http.target` (route template), `http.response.status_code`, `http.url` **without the query string**, network peer |
| `SELECT` / `INSERT` / `UPDATE` / `DELETE` | `tracing.instrument_engine` (SQLAlchemy engine events) | `db.system`, `db.operation`, `db.statement` (string literals replaced by `'?'`, capped at 300 chars), `db.executemany` |
| `llm.generate` | `services/tutor.py` `_generate` | `llm.provider`, `llm.model` |
| `ai_job.run` | `routers/workspace.py` `_execute_ai_job` | none (job kind/id are already in the structured log line) |

Not traced: `/health`, `/live` (scrape volume, no diagnostic value) and
`/metrics`. The ASGI `send`/`receive` child spans are disabled — on the SSE
path they are one span per chunk.

### Per-stage records (unchanged by the OTel work)

Set `TRACING_ENABLED=true` and every ask emits:

```json
{"event": "trace", "stage": "retrieval", "trace_id": "…",
 "retrieval_ms": 41, "evidence_chunks": 3, "top_score": 0.72,
 "coverage": 0.91, "gate": "pass",
 "index_version": "HybridIndex:2504:9f2c…", "stream": false,
 "retrieved_ids": ["nctb-…-0042", "…"], "request_id": "…",
 "otel_trace_id": "…", "otel_span_id": "…"}
```

| Question | Answer source |
|---|---|
| Which corpus produced this answer? | `index_version` (class, chunk count, sha256 of the chunk-id set) |
| Which prompt text? | `prompt_version` (prompt id plus the sha of the system prompt in this build) |
| Which chunks were retrieved, and how did the gate vote? | `retrieved_ids`, `gate`, `coverage`, `top_score` |
| What did it cost? | `prompt_tokens` / `completion_tokens`, same estimator as the ledger |
| How do I join the stages of one ask? | `trace_id` — the request id, matching `X-Request-ID`, the access line and any 500 body |

Implementation: `logging_config.trace_event` (behind the flag),
`middleware.RequestIdMiddleware` (trace-id seed), `services/tutor.py`
(`_trace_retrieval`, `_trace_generation`).

## Switching tracing on

| Variable | Effect |
|---|---|
| `TRACING_ENABLED=true` | master switch. Without it `tracing.py` installs nothing: no provider, no instrumentation, no span objects (tests assert both states). |
| `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`) | where spans go. **No endpoint means no export**: spans are created and dropped in process, which is the staging/test posture. |
| `OTEL_SERVICE_NAME` | overrides `service.name` (default: the app name). |
| `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG` | sampling policy. Default `parentbased_always_on`; `parentbased_traceidratio` with an arg in `0..1` for volume control. |
| `OTEL_SDK_DISABLED=true` | hard off, even when the other variables are set. |

The OTLP/HTTP exporter batches (5 s flush). A collector that is down never
affects a request: the SDK drops failed exports, and a failed
provider/exporter **initialisation** is logged (`tracing_exporter_init_failed`)
and ignored.

### Verifying without a collector

```bash
# one request, real spans, no collector:
.venv/Scripts/python -m pytest tests/test_i2_tracing.py -q
```

The tests attach an `InMemorySpanExporter` to the same provider the app uses
and assert span names, attributes, parent/trace relationships, the no-op state
when tracing is off, and that no PII (question text, email address, API key,
query string) appears in any attribute.

## Privacy rules (minors-facing product)

* **No question or answer text** on a span or a trace record: the LLM span
  carries provider/model only, the DB span carries the statement with string
  literals replaced by `'?'`, and the per-stage records carry counts and ids.
* **No query strings**: `/search?q=…` would put a student's wording into
  `http.url`; the server-request hook strips everything after `?`.
* **No headers, no cookies, no bodies**: the ASGI instrumentation captures
  none of them, and SQLAlchemy parameters are never recorded.
* **Attribute filter**: `tracing.span(**attributes)` drops any key the log
  redactor treats as sensitive (`logging_config.is_sensitive_key`), so a
  future call site cannot export a token by accident.

## Trace-log correlation

Every structured log line emitted while a span is active carries
`otel_trace_id` and `otel_span_id` (`logging_config.json_log`). The field
names are deliberately not `trace_id`/`span_id`: `trace_id` has meant "the
request-level correlation id" since AUD-HI-18, and operator queries use it.

Joining the two worlds:

* log line → trace: take `otel_trace_id` and look the trace up in the
  collector;
* trace → logs: the access line and every per-stage record of one request
  carry the same `trace_id` (the request id), so one
  `grep '"request_id": "<id>"'` reconstructs the pipeline.

Work outside a request (a job with no parent, a script) still gets its own
trace id via `logging_config.new_trace_id`.

## Client-side telemetry (I-12)

The web app's Sentry client and web-vitals RUM are consent-gated: nothing is
sent unless the user (or guardian) opts in, the decision lives in
`localStorage["bgpt.telemetry.consent"]`, and error payloads are scrubbed of
user identity, request bodies, cookies, headers and URL query strings. The
implementation is specified in `.audit/handoffs/g2-from-i2.md` (web files are
owned by the frontend workstream).

Server side has nothing to add: browser telemetry goes to Sentry's own
backend, and the product-event route (`POST /events`) already sanitizes props
server-side (PII-hint keys dropped, primitives only, 40-char cap —
`routers/common.py` `_sanitize_event_props`).

## Cost and volume notes

* One server span plus a handful of DB spans per request; the DB span count
  tracks the statement count, and the heaviest read paths are the dashboard
  fan-outs (see `docs/operations/PROFILE.md`).
* `otel_trace_id`/`otel_span_id` add two fields to existing log lines, not
  extra lines. The per-stage records remain the verbose layer and stay behind
  `TRACING_ENABLED`.
* Sampling is the production knob: keep `parentbased_traceidratio` at a rate
  the collector can store, and sample by trace id so a whole request is kept
  or dropped together.
