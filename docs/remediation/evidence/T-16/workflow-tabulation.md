# CI workflow tabulation — T-16

Audited at HEAD `31e3e60ba51b9dde54cfbcba0de4466f70c83917`, 2026-11-19. Every fact below was read from `.github/workflows/*.yml` this session (H-1 `[F: workflow:lines @31e3e60]`); line references are exact.

## Per-workflow table

| Workflow | Jobs | Timeout-minutes | Top-level permissions | Triggers | Third-party action pinning | continue-on-error | Notes |
|---|---|---|---|---|---|---|---|
| ci.yml | api (matrix 3.11+3.12), quickstart-windows, postgres, sbom, eval (reusable call), web, guardrails, e2e, e2e-engines, docker | every job (10–60 min) | `contents: read` | push/PR main + workflow_dispatch | all `uses:` pinned to full SHA with version comment; container images digest-pinned | none | `persist-credentials: false` on every checkout; Redis service in api job; Q-19 satisfied |
| eval-gate.yml | eval-gate | 15 | `contents: read` | push/PR main, workflow_dispatch (real_model input), workflow_call | pinned | 1 leg: real-model probe (`:119`), **manual-dispatch only, documented informational** | secrets: GEMINI_API_KEY via workflow_call, never on push/PR legs |
| codeql.yml | analyze | 30 | `contents: read`; job: `security-events: write`, `pull-requests: read` | push/PR + workflow_dispatch | pinned | none | scoped job permissions |
| scorecard.yml | scorecard | 20 | `read-all`; job: `security-events: write`, `contents: read` | branch_protection_rule + schedule + push + workflow_dispatch | pinned | none | |
| secret-masking.yml | 2 jobs | 5, 10 | `contents: read` | (test workflow) | n/a (no actions) | none | uses a DUMMY test secret |
| automerge.yml | arm | **MISSING** | `contents: write`, `pull-requests: write` (justified in-file with measured evidence; fork PRs excluded at `:if`) | pull_request (types…) + workflow_dispatch — **not** pull_request_target | no actions used | none | the one Q-19 gap found |
| uptime.yml | 3 jobs | 5 each | `contents: read`, `issues: write` (paging via issues, justified) | schedule + workflow_dispatch | pinned | none | |
| retrieval-eval.yml | 1 job | 30 | `contents: read` | workflow_dispatch (+ require_corpus fail-closed) | pinned | none | |
| vercel-deploy.yml | deploy | 15 | `contents: read` | workflow_dispatch/push (production environment) | vercel CLI version-pinned via npx | 1 leg: API-health smoke (`:159`), **documented deliberately non-blocking** — API origin down is not a web-deploy failure; API health has own gates | secrets can't be read from forks (documented `:122`) |
| android-release.yml | 1 job | 2 occurrences | `contents: read` | tag/push with `paths:` filter (`:46`) | pinned | none | the only path-filtered trigger (release artifact paths) |
| release.yml | several | 4 occurrences | `contents: read` (job-level scopes inside) | tag push | pinned | none | `environment: production` at `:432` |

## Card-step findings

1. **Required jobs**: per ci.yml:495-503, branch protection's required contexts are the ci.yml jobs (api, quickstart-windows, postgres, sbom, eval→web chain, guardrails, e2e, e2e-engines, docker). Changing required-check settings is HO-2 (branch protection is a repo setting, T-16 Never).
2. **continue-on-error**: exactly 2 legs repo-wide (eval-gate.yml:119, vercel-deploy.yml:159). **Neither gates correctness** — one is a manual-dispatch informational probe, the other a documented post-deploy smoke whose failure mode (API origin down ≠ web deploy failure) is reasoned in-file. Per card step 2(b) ("remove `continue-on-error` from jobs that gate correctness") neither is removed; both are recorded here with their reasons.
3. **Coverage threshold**: API `fail_under = 80` (pyproject.toml:303) vs T-00 measured **89.52%** → raise to **89**. Web vite thresholds (lines 68 / functions 60 / branches 60 / statements 70, vite.config.ts:165-169) vs T-00 measured (78.94 / 72.27 / 70.07 / 76.76) → raise to **78 / 72 / 70 / 76**. Both are the larger-of rule, measured by the exact method CI uses (T-00 CI-exact capture `EV-T00-api-coverage`, `EV-T00-web-coverage-verified2`).
4. **Type-check strictness**: mypy per-flag strictness (strict_equality, strict_bytes, …; pyproject:338-352) — unchanged, no loosening.
5. **Lint rules**: ruff select list incl. S/B/ERA/C901; eslint type-aware `--max-warnings 0` — unchanged.
6. **DB tests on Postgres**: **already satisfied** — `postgres` job runs the alembic up/down/up cycle, `alembic check`, pgvector integration tests, Postgres-only race tests, and the **full domain suite on Postgres** (1106 tests measured in-file; ci.yml:408-431). No change needed.
7. **Path-filtered jobs**: only android-release.yml:46 (release-artifact paths — appropriate for a release workflow). No required check can skip silently by path filter. Event-filtered: e2e-engines (`pull_request` only) — a deliberate companion pass, not a required-check skip.
8. **Action pinning**: zero unpinned `uses:` across all 11 workflows (measured by grep). Docker images digest-pinned.
9. **Permissions**: minimal everywhere; the two write grants (automerge, uptime) are in-file justified; fork PRs excluded from automerge; `persist-credentials: false` on all ci.yml checkouts.
10. **Triggers**: no `pull_request_target` anywhere (measured). No secrets reachable from forks (vercel-deploy documents the fork-secret rule at :121-122).
11. **Timeouts**: present in every job of every workflow **except automerge.yml** → fix (tightening).

## Tightenings applied by T-16

| Change | File | Rationale |
|---|---|---|
| `fail_under` 80 → 89 | apps/api/pyproject.toml | larger-of rule vs measured 89.52 (T-00) |
| vite thresholds → 78/72/70/76 | apps/web/vite.config.ts | larger-of rule vs measured 78.94/72.27/70.07/76.76 (T-00) |
| stale comment refresh | .github/workflows/ci.yml:541-544 | the threshold numbers it quotes change |
| `timeout-minutes: 5` on automerge job | .github/workflows/automerge.yml | the one missing Q-19 timeout |

Per-module FLOORS file (`apps/api/scripts/check_coverage_floors.py`) intentionally NOT touched: AGENTS.md §11 reserves it for the QA Engineer role and card step 2(a) names the single threshold; recorded as a deviation note in STATE.md.
