# Backend audit — 2026-11-18

Enterprise-standard QA and audit of the complete backend condition (`apps/api`
and the CI gates that guard it), requested by the owner with a full execution
mandate. This register supersedes the 2026-11-17 assessment where the two
disagree; the 2026-11-17 stack research is carried forward in the companion
plan (`audit-2026-11-18-remediation-plan.md`).

## Method and evidence boundaries

Four evidence channels, each marked where used:

1. **Direct measurement** — commands run in this session (counts, greps,
   targeted test runs, YAML validation).
2. **Specialist read-only audits** — a security-reviewer audit (controls,
   secrets, boot guards; 14 control areas re-verified with file:line
   evidence), a qa-engineer audit (test infrastructure, ratchets,
   flakiness safeguards), and a devops-engineer audit (release gating,
   topology, Docker/compose; `actionlint` rc 0 across all 11 workflows,
   real Trivy failure-injection runs, a real gitleaks full-history scan,
   and measured GitHub API run counts). All ran with read-only constraints
   and returned evidence-backed findings.
3. **Baseline gates executed locally** — ruff, ruff format, mypy, the full
   pytest suite with coverage (final numbers below), plus the in-flight
   release-gate repairs validated by YAML parse and logic review.
4. **Prior measurements** — the 2026-11-17 audit and RAG V5 records,
   re-checked where quoted.

**Not determined / not run:** `lint-imports` is not installed on this
machine (CI-only gate); pip-audit/semgrep/Trivy/CodeQL were not run locally
(CI covers them); the DevOps/release-establishment sequence is recorded in
the plan as the remaining 0.15.0 step. The full-suite coverage result is
quoted from this session's run; anything older is dated.

## Executive summary

**No P0 defect found** — consistent with the 2026-11-17 audit. The two known
P1s stand: the live topology runs SQLite while the designed topology is
Postgres (owner decision), and the arq worker had no metrics exposure
(**remediated in this change**). The audit found **four new P2s** and a set
of P3s; three P2-class items shipped their fixes in the same change as this
audit (worker metrics, Postgres `statement_timeout`, Sentry sample-rate
setting), and one test-infrastructure P2 (coverage-floor blind spot) got its
floor and branch tests. Everything else is scheduled in the companion plan.

The in-flight `fix/release-gates-0.15.0` repairs (Trivy DB-flake retry,
CodeQL `workflow_dispatch`, gitleaks allowlist) were audited and are
**fail-closed sound**: the Trivy retry fires only on the exact
vulnerability-DB download error and a scan that found a fixable
HIGH/CRITICAL still fails on the first attempt; the CodeQL trigger addition
weakens no permission or path; the gitleaks entry is value-scoped to one
zero-entropy placeholder literal (and is documented as version-drift
insurance after measurement showed the original finding no longer
reproduces under gitleaks 8.30.1).

## Findings register

Severity: P0 blocker / P1 major / P2 moderate / P3 minor. Status:
**fixed-in-this-change**, *scheduled* (companion plan wave), or *owner
decision*.

| ID | Sev | Finding | Evidence | Status | Effort |
|---|---|---|---|---|---|
| F-1 | P1 | Live topology is SQLite; designed topology is Postgres (`runbook.md` §7.3 vs `backup_dr.md`) — backup coverage, concurrency and pgvector readiness all hang on this | `main.py:257-276` accepts file SQLite in production; `docs/runbook.md` §7.3 | owner decision (Wave D) | L |
| F-2 | P1 | arq worker exposed no metrics; job outcomes only in logs — a silently failing retention sweep was found by users | `worker.py` pre-change; 2026-11-17 audit | **fixed-in-this-change** (metrics server + counters + alert) | — |
| F-3 | P2 | Password policy default (8) is below the NIST single-factor floor (15) while MFA is optional; no boot guard ties the two | `config.py:265` default; `auth/security.py:40-45` documents 8 as deliberate; `main.py` validators have no password gate | owner decision (Wave A records it) | S |
| F-4 | P2 | Audit log append-only is application convention only; no DB-level backstop (trigger/REVOKE) — the sole mutation site is the documented erasure anonymization | `db/models.py:1013-1035`; sole mutation `services/gdpr.py:971` | scheduled (Wave A design spike) | M |
| F-5 | P2 | Email-verification integration tests (Mailpit-gated) never execute in CI — no workflow starts Mailpit, so the autouse fixture always self-skips | `tests/test_w2_authz_email_verify.py:76-84`; no `mailpit` in `.github/workflows/` | scheduled (Wave A) | M |
| F-6 | P2 | No Postgres `statement_timeout`: a runaway statement held a pooled connection indefinitely | `db/session.py` pre-change (`connect_args` had `connect_timeout` only) | **fixed-in-this-change** | — |
| F-7 | P2 | Sentry `traces_sample_rate` hardcoded 0.1 at the init site | `initialize/observability.py:64` pre-change | **fixed-in-this-change** | — |
| F-8 | P2 | `initialize/observability.py` unfloored (sibling `schedulers.py` was floored) and its no-DSN/init-failure branches untested | `check_coverage_floors.py` FLOORS pre-change; partial-run coverage 70.73% | **fixed-in-this-change** (floor 100 + branch tests) | — |
| F-9 | P3 | The new gitleaks allowlist entry cleared nothing measurable (finding does not reproduce under gitleaks 8.30.1 in git or dir mode) | measured full-history scans, both configs, 0 leaks | **addressed** (comment states the measurement; entry kept as version-drift insurance) | S |
| F-10 | P3 | Worker metrics endpoint unauthenticated (differs from API `/metrics` token gate) | `worker.py` `_start_worker_metrics_server`; compose publishes no host port | **addressed** (posture documented at `config.py` field; compose-network-only, counters only) | S |
| F-11 | P3 | CI pytest seed never rotates (`--randomly-seed=20261030` on every leg) — ordering exploration depends on unpinned local runs | `ci.yml` six legs | scheduled (Wave A, S) | S |
| F-12 | P3 | No parallelization readiness: no pytest-xdist; Playwright `workers: 1` | `pyproject.toml` dev extras; `playwright.config.ts:95-96` | scheduled (Wave A backlog) | M |
| F-13 | P3 | Flat 265-file test layout; 115 files import conftest as a module | `find apps/api/tests -maxdepth 1`; grep count | scheduled (bundled with F-5 tiering) | M/L |
| F-14 | P3 | `test_architecture_hardening.py:83-93` asserted a constant equals itself and read `engine.pool._creator` internals | QA audit | **fixed-in-this-change** (kwargs pinned in `test_db_statement_timeout.py`) | S |
| F-15 | P3 | `normalize_idempotency_key` ASCII-pattern branch untested | QA audit | **fixed-in-this-change** | S |
| F-16 | P3 | `gitleaks dir` without `--config` silently scans under default rules | security audit measurement | scheduled (Wave A Makefile target, S) | S |
| F-17 | P3 | env-matrix.md `config.py` line citations drift as the file grows | known; bulk fix reverted as churn 2026-11-17 | owner follow-up (unchanged) | — |
| F-18 | P2 | `vercel-deploy.yml` never auto-fires for bot-merged commits: its `workflow_run` filter requires `event == 'push'`, and bot merges produce zero ci.yml push runs (measured) — the runbook §7.1 "automatic deploy on the merged main commit" claim is false for them | `vercel-deploy.yml:33-38`; DevOps measurement of `d14daef` | scheduled (Wave A: amend filter or document the dispatch step) | S |
| F-19 | P2 | `android-release.yml`'s `v*` tag path has no CI gate — a signed AAB is produced for any tagged commit regardless of CI state; only the human Play Console upload controls it | `android-release.yml:42-44` vs `release.yml`'s gated `build-push` | scheduled (Wave A: gate it or document) | S |
| F-20 | P3 | Release-gate unsatisfiability measured, not just inferred: 0 runs of ci.yml + codeql.yml + eval-gate.yml on origin main tip `d14daef` (bot-merged, GITHUB_TOKEN anti-recursion) — CI-FIX-014 is the codeql half; ci.yml/eval-gate.yml already dispatchable | `gh api runs?head_sha=d14daef` ×3 → 0 | **addressed-in-this-change** (fix merged via this branch; dispatch sequence in the plan) | S |
| F-21 | P3 | `--skip-dirs node_modules --skip-dirs dist` inert for the single-file Trivy fs target (misleading, harmless) | real Trivy run output in the DevOps audit | accepted (kept: future-proofs a dir target) | S |
| F-22 | P3 | `WorkerJobsFailing` alerts only on `failed` — a cancelled (timed-out) digest does not page; max_tries exhaustion is covered transitively (each attempt counts `failed`) | `deploy/prometheus/alerts.yml:86` | accepted (cancelled also fires on routine shutdown-cancellations during deploys — alerting it would page on every deploy; the series exists for dashboards) | S |
| F-23 | P3 | Worker metrics bind failure fails worker boot (fail-closed: a port conflict becomes a jobs-schedule outage, not just missing metrics) | `worker.py` `_start_worker_metrics_server` inside arq `startup` | accepted (documented posture; compose fixes the port per profile) | S |
| F-24 | P3 | Web image nginx master runs as root (official-image default) while the API image is rootless 10001 | `apps/web/Dockerfile` (no USER) | scheduled (Wave A backlog) | M |

## Measured counts (2026-11-18)

| Metric | Value | Command |
|---|---|---|
| DB tables | **44** | `grep -c "__tablename__" apps/api/src/bangla_gpt_api/db/models.py` |
| Alembic revisions | **39**, single head `c7d9e1f3a5b7` | file count + down_revision graph parse |
| API test files | **265** | `find apps/api/tests -name "test_*.py" \| wc -l` |
| Collected tests | **2318** | `pytest --collect-only -q` |
| Floored modules | **29** (was 28; +`initialize/observability.py`) | `check_coverage_floors.py` |
| mypy | 141 source files, no issues | `mypy src` |
| ruff | all checks passed; 446 files formatted | `ruff check . && ruff format --check .` |

AGENTS.md §10/§12's own counts (42 tables, 36 revisions, 252 test files) are
stale against these measurements; the file invites re-counting and this
document is the current reference.

## Controls verified intact (highlights)

Security axis (14 areas re-verified with file:line evidence — see the audit
session record for the full list): Argon2id OWASP parameters + rehash-on-verify;
Fernet PII encryption with refusal-to-store and the production `PII_ALLOW_PLAINTEXT`
boot refusal; single-use tokens as SHA-256 hashes only with atomic fail-closed
claims; consent versioning enforced as a gate (not a display field); audit log
five privileged event types with id-only details; retention windows unchanged;
GDPR export/erasure completeness (`test_export_completeness.py` passed);
per-kind PII redaction metered before egress; every `enforce_production_safety`
validator present and fail-closed; authorization helpers used throughout with
every inline role check a documented post-authorization refinement; JWT
issuer/audience/jti-revocation posture; rate limiting fail-closed; secrets
hygiene (compose interpolation, empty production-template secrets, full-history
gitleaks scan clean over 1162 commits).

QA axis: all six §11 per-module floors exact-match and raise-only; web vitest
thresholds 68/60/60/70 intact; zero xfails, all skips environment-conditional;
`check_vitest_ran.mjs` completeness gate on both vitest entry points; e2e port
separation intact; three-engine Playwright wired on PRs. The prior audit's
"integration marker unused" is stale — 3 usage sites now, 2 of which run in CI.

RAG axis (direct spot-checks): grounding gate constants unchanged
(`min_coverage=0.5`, `top_k=3`, out-of-corpus absent budget —
`services/tutor.py:533-534,727-754`); helpline numbers pinned
(`services/safety.py:37-38`); per-kind PII metering intact; eval artifacts
present (`baseline_v3.json`, `golden_v3.json`, `redteam_v2.json`).

## Baseline gate evidence from this session

- `ruff check .` + `ruff format --check .` — passed (all files).
- `mypy src` — `Success: no issues found in 141 source files`.
- Full API suite with coverage — executed (final numbers recorded in the
  remediation-plan execution report; the run predates the last test-file
  additions, which were separately run green: 33 tests across the four touched
  files, plus 8 in `test_architecture_hardening.py`).
- YAML parse: `ci.yml`, `codeql.yml`, `docker-compose.yml`,
  `deploy/prometheus/prometheus.yml`, `deploy/prometheus/alerts.yml` — all OK.
- Targeted suites re-run after every change; final targeted result
  **33 passed** (`test_worker_spine`, `test_qa_sentry_scrub`,
  `test_db_statement_timeout`, `test_w2_db_ai_jobs`).
