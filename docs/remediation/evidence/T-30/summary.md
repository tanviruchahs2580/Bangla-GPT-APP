# T-30 — observability: PARTIAL (inventory complete; OTel deferred; promtool BLOCKED)

Verified 2026-11-20 at `8717f6f`.

## Existing inventory (card step 1)
- Prometheus metrics: `metrics.py` + PROVIDER_LATENCY_SECONDS + CACHE_EVENTS_TOTAL + worker metrics (wave: 94a76cb); `/metrics` production-token-gated (system.py:145-146).
- Logging: structured json_log with context fields (route/ids/counts, never content) + secret-safe gate (logging_config).
- Sentry: `initialize/observability.py` (rate setting configured, scrub tests green).
- Alert rules: `deploy/prometheus/`, `deploy/alertmanager/` exist.
- Per-stage latency: evaluation latency report (RAG-26) + provider latency histograms.
- Provider-reported tokens: NOW logged per generation post-T-23 (`usage_source` + counts) — the card's "extend the existing Prometheus metrics with provider-reported tokens" is satisfied at the log layer; a Prom counter addition is a follow-up.

## Not shipped here (with reasons)
1. **OpenTelemetry spans**: adding `opentelemetry-sdk` is a new runtime dependency requiring a `pip-compile` regeneration of the 192 KB hash-pinned `constraints.txt` (a lockfile churn with supply-chain review of its own) AND the exporter-default decision is BC-6 territory (disabled by default is required; enabling it anywhere is S-3). Recorded as the follow-up with this rationale — NOT silently skipped.
2. **Alert-rule unit tests**: `promtool` is UNAVAILABLE on this machine (T-00 capability matrix) → **BLOCKED** per the card's own rule; the exact command a human must run: `promtool test rules deploy/prometheus/rules/*.yml` (or add a CI step on an image carrying promtool).
