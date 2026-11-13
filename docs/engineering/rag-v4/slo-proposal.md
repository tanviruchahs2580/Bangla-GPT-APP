# SLO proposal — RAG V4 Phase 9 (PROPOSED — owner approval required)

Date: 2026-11-13. **These are proposals, not commitments.** Per the master
prompt: measure baseline first, and owner approval is required before SLOs
become commitments with alerting. Where a baseline exists below, it is the
hermetic/local measurement noted — it is NOT a production baseline; the
production topology is single-host SQLite behind a rotating tunnel, which
makes some targets genuinely unknown until measured there.

## Existing signals (verified)

- `/health` (production alias verified 200×2 on 2026-11-13); `/status` with
  real component checks (ANON-02 e2e); `/metrics` token-gated in production.
- Structured logs with PII redaction; low-cardinality metrics; SSE + JSON
  refusal envelopes carry machine-readable `refused_reason` (S8).
- AnswerTraceStore records outcome/chunk_ids/scores/grounded/latency
  in-process (evaluation observability).

## SLI / SLO proposals

| # | Indicator | Proposed objective | Baseline today | Notes |
| --- | --- | --- | --- | --- |
| 1 | Successful tutor-request rate (HTTP 200 + contract-valid body, mock-agnostic) | ≥ 99% over 28 days | UNSCORED in production | hermetic traces 27–82 ms are not a production baseline |
| 2 | Tutor end-to-end latency p95 (excluding model time; model timeout separate) | propose p95 < 3 s server-side | UNSCORED | model timeout is provider-config; proposal: it must be bounded and logged |
| 3 | Grounding-gate honesty: zero fabricated-source citations in citation tests | 0 (hard gate, already test-pinned) | VT — sources are server-populated from chunk metadata; citation_validator computed-not-blocking is test-pinned deliberate | blocking behavior change = owner decision |
| 4 | Appropriate-refusal vs false-refusal reported separately | both reported per release | hermetic golden: gate-refusal 24.1%, of which 20.2 pp false-refusal on answerable items | honesty rule: never publish refusal rate without the split |
| 5 | Provider error rate / quota exhaustion | alert at sustained > 1% over 10 min | UNSCORED | requires live provider config (owner) |
| 6 | Worker queue age/depth (ai_jobs, 30-day retention) | age p95 < 5 min; depth alert on sustained growth | UNSCORED | inline jobs backend in tests; Redis/ARQ in prod |
| 7 | Ingestion freshness + manifest integrity | manifest check green per corpus change (already CI-blocking) | VT (CI-FIX-001) | no change proposed |

## Alert proposals (each with an actionable runbook or "runbook required before enabling")

| Alert | Severity | Rationale / false-positive note | Owner |
| --- | --- | --- | --- |
| /health failing 3× | high | the one alert already exercised (tunnel rotation incident 2026-11-13, repaired twice) | owner |
| Tutor 5xx rate > 1% over 10 min | high | excludes intentional 4xx refusals; refused_reason has its own counter | owner |
| SSE stream error-frame rate spike | medium | S8 made error frames countable; distinguish provider outage (circuit breaker) from client aborts | owner |
| ai_jobs stuck in non-terminal > 30 min | medium | matches 30-day retention semantics; actionable: inspect worker, restart, dead-letter count | owner |
| Rate-limit 429 surge | low | usually legitimate exam-eve demand; page only if sustained | owner |

No alert is created noisy without an actionable response: the two "medium"
alerts require runbook entries (model-provider outage; queue degradation)
to exist in `docs/runbook.md` before being wired. Detection → containment →
owner → recovery → verification → communication fields are defined in the
incident doc proposal (`docs/ai/incident-response.md`), which remains
owner-unapproved.

## Backup / restore / rollback evidence (Phase 9 §12.4)

- Pre-swap DB snapshot + restore_test **PASS** recorded 2026-11-12 19:54
  (production read-only evidence, before build 0.10.0-d6f3342).
- Rollback container kept stopped (`api-live-pre-auditfix`); runbook §7.1
  documents the hand-run swap; §7.3 records the live-API-runs-SQLite fact.
- **Restore end-to-end is UNTESTED on the live topology** (no `psql`/
  `sqlite3` client on this machine; AGENTS §15). Marked BLOCKED — not
  claimed.
- RPO/RTO: **unknown until owner-approved targets exist**; no invented
  numbers.

## Load/failure testing status

Local evidence: e2e resilience suite (slow API, failing API + retry, offline
banner, slow-3G flows, permission-denied, empty-state), 4x/6x CPU-throttled
perf specs in CI, JS-heap boundedness, per-IP limiter 429 behavior (ANON-04).
NOT DONE locally/anywhere: realistic concurrency soak, DB-pool saturation,
provider slow/fail matrix, queue backlog + worker restart — environment
limits (single workstation, SQLite, no provider credentials) documented;
no capacity claims extrapolated.
