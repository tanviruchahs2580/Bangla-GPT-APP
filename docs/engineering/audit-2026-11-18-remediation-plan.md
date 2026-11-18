# Backend remediation plan — 2026-11-18

Companion to `audit-2026-11-18-backend.md`. Ordered waves, each with scope,
acceptance criteria and its gate. Sequenced by risk-adjusted value: the
executed wave first, then the cheapest high-value work, then the waves whose
gating requirements are explicit.

## Wave 0 — executed in this change (branch `fix/release-gates-0.15.0`)

| Item | What landed | Verification |
|---|---|---|
| CI-FIX-013 (in-flight, audited) | Trivy vulnerability-DB flake retry, fail-closed (only the exact DB-download error retries; a real finding still fails first attempt; 3 failed attempts exit 1) | YAML parse; security-audit logic review; mocked-scenario matrix from the prior session |
| CI-FIX-014 (in-flight, audited) | CodeQL `workflow_dispatch` so the release gate can be satisfied for bot-merged main commits | YAML parse; release.yml gate trace (event type not restricted; permissions unchanged) |
| gitleaks entry (in-flight, corrected) | Value-scoped allowlist for the F-107 fixture literal, now documented with the measured 8.30.1 result | full-history scans with both configs: 0 leaks |
| F-2 worker metrics | `WORKER_METRICS_PORT` (Settings, default 0), `start_http_server` on `metrics.REGISTRY` in `worker.startup`, `bgpt_worker_jobs_total{job,outcome}` + `bgpt_worker_job_duration_seconds`, compose worker default 9101, Prometheus `bangla-gpt-worker` scrape, `WorkerJobsFailing` alert, runbook §5 + env-matrix rows | 10 worker-spine tests incl. outcome/delta metering; YAML parse |
| F-6 statement_timeout | `POSTGRES_STATEMENT_TIMEOUT_MS` (Settings, default 30000, 0 disables) via libpq `options` on the Postgres branch of `make_engine` | 4 kwargs-pinning tests (monkeypatched `create_engine`) |
| F-7 Sentry sample rate | `SENTRY_TRACES_SAMPLE_RATE` (Settings, default 0.1, clamped [0,1], invalid→0.1) consumed by `configure_sentry` | 4 scrub-file tests incl. clamp + fallback paths; module at 100% measured |
| F-8 coverage floor | `initialize/observability.py: 100.0` floor (CI-FIX-015) + no-DSN / init-failure / combined-entry tests | partial-run coverage 100%; floor script pattern match |
| F-14/F-15 test gaps | kwargs-pinned Postgres posture test replaces the self-referential assertion; `normalize_idempotency_key` pattern-branch unit tests | 8 + 1 tests pass |
| Docs | `audit-2026-11-18-backend.md`, this plan, runbook §5, env-matrix rows | — |

**Wave 0 acceptance:** ruff + ruff format + mypy clean; targeted suites green;
full suite + coverage green; YAML valid; CHANGELOG regenerated; CI green on
the PR before merge.

## Wave A — next cheapest high-value work (no lockfile touch)

1. **Mailpit in CI (F-5, M).** Add a pinned `axllent/mailpit` service
   container to the API test jobs (or a dedicated `-m integration` job).
   Acceptance: `test_w2_authz_email_verify.py` executes (not skips) in CI;
   the skip fixture stays as a local-dev fallback.
2. **Audit-log DB enforcement design spike (F-4, M).** Dual-dialect trigger
   design (SQLite + Postgres) with the erasure-anonymization carve-out
   (session flag or definer helper); rehearse on a disposable DB; separate
   approval gate before any migration runs — audit-log policy is an explicit
   §14 approval boundary.
3. **Password-policy decision record (F-3, S).** Record the owner decision:
   either raise the single-factor floor to 15 (with a boot validator shaped
   like `_validate_ai_budget`), or accept 8 with MFA adoption tracked in the
   risk register. `auth/security.py:40-45` documents 8 as deliberate — this
   wave only records the decision, it does not silently change the contract.
4. **Deploy-path gates for bot merges (F-18/F-19, S each).** Either amend
   `vercel-deploy.yml`'s `workflow_run` filter to accept dispatched runs (or
   document the manual dispatch as the standing step), and gate
   `android-release.yml`'s tag path on the same three-workflow evidence
   `release.yml` requires — a signed AAB must not exist for a commit CI
   never saw.
5. **CI seed rotation (F-11, S).** `--randomly-seed=${{ github.run_id }}`
   with the seed echoed into the job summary (pytest-randomly prints it) —
   reproducibility preserved, ordering exploration restored.
6. **gitleaks Makefile target (F-16, S).** `make gitleaks` always passing
   `--config .gitleaks.toml`.
7. **Web image rootless (F-24, M).** nginx unprivileged-user runtime to
   match the API image's UID-10001 posture.

## Wave B — dependency refresh + installer modernisation (lockfile wave)

From the 2026-11-17 stack research, re-affirmed: patch refresh
`fastapi==0.163.1`, `SQLAlchemy==2.1.9`, `sentry-sdk==2.75.0` via the
sanctioned `constraints.txt` regen (hash-pinned, `check_lockfile.py`
verified); **uv** as dev+CI installer (`uv pip sync --require-hashes`;
`constraints.txt` stays the artifact authority); real OTel wiring
(`opentelemetry-sdk` + `opentelemetry-instrumentation-fastapi` — only the
transitive `opentelemetry-api` is pinned today, so nothing emits spans);
`structlog` for processor-level PII enforcement.

**Gate:** this wave touches the hash-pinned lockfile — it ships as its own
reviewed change with the full gate set, never bundled with behaviour changes
(supply-chain rule + §14).

## Wave C — RAG quality gates (from the 2026-11-17 master plan)

Real-corpus CI eval leg (the blocking gate's synthetic-sample limitation is
on record), the citation-validator blocking decision (`RAG_CITATION_CHECKS_TOTAL`
is metered but does not block), and the pre-v2 R@1 regression investigation.
Never in the same PR as a baseline regeneration (§11).

## Wave D — infrastructure decisions (owner)

Postgres host selection + migration plan (F-1; the pgvector readiness
checklist is the same work), corpus off-site backup via the existing
`s3_corpus_sync.py`, DPIA completion (the known governance gap for a
children's-data product), and Wave A item 2's migration execution after its
rehearsal.

## Modern-stack verdict (late-2026 research, re-affirmed 2026-11-18)

**ADOPT:** the patch refreshes above, uv, real OTel wiring, structlog.
**HOLD:** pgvector 0.8.7 (needs the Postgres host AND is manifest-breaking),
pgvectorscale (early stage), arq→taskiq (arq is maintenance-only and caps
redis-py <6; trigger only on need), Redis 8/Valkey.
**AVOID:** async SQLAlchemy rewrite (repo forbids), framework/ORM swap,
Celery (oversized), NoSQL, redis-py 6 (arq ceiling), Sentry 3.x (not final),
microservices.

The existing stack is already modern for its scale: FastAPI ≥ 0.115,
SQLAlchemy 2 sync, Pydantic v2 settings, Alembic, arq + redis, Prometheus
metrics + alert rules, Sentry with PII-scrubbing `before_send`, and a
grounding-gated RAG lane. The honest "modernisation" here is the patch
refresh + observability completion above — not a rewrite. Rewriting would
break the §5/§6/§7 invariants that make the product safe for children's data.

## Standing anti-recommendations (unchanged)

No gate weakening, no threshold lowering, no baseline regeneration to pass a
gate, no async rewrite, no framework/ORM swap, no Tailwind/second state lib,
no PDF-font substitution, no retention-window shortening, no helpline edits.
