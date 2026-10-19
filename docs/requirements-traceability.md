# Requirements traceability matrix (RTM)

Status: living document. Owner: QA / release engineering. Companion to
`docs/testing-strategy.md`.

Each row maps a **catalog item** (the audit's requirement IDs from
`.audit/master-prompt.md` §7, tracked in `.audit/catalog-status.csv`) to the
**test artifact** that satisfies it and the **gate** that runs it. "Artifact"
means a concrete file (and, where it matters, a test node) that a reviewer can
open and run; a row without one is a gap, and the gaps are listed at the end
rather than hidden by a generic phrase.

Status vocabulary:

- **VERIFIED** — the artifact exists in this tree and was executed during the
  remediation pass; the evidence ID is recorded in `.audit/evidence/`.
- **PARTIAL** — the artifact covers part of the requirement; the residual is
  named in the row and listed in `docs/testing-strategy.md` §8.
- **GAP** — no artifact; owner and next step named.

---

## 1. Domain E — testing (catalog items E-01 … E-20)

| Item | Requirement (abridged) | Test artifact / gate | Status | Evidence |
|---|---|---|---|---|
| E-01 | Test inventory per layer with counts, runtime and flakiness; every skip has a reason and an issue | `.audit/evidence/E-V1-040-full-pytest-final.txt` (suite inventory); skip reasons enumerated in the run summary; `apps/api/tests/conftest.py` documents the env-conditional PG/Redis guards | PARTIAL | E-E-001, E-EF-021 |
| E-02 | Pyramid balance and speed; no order dependence | `pytest -p no:randomly` full run; seeded random-order runs in `.audit/evidence/E-EF-024-*`, `E-EF-025-*`; `conftest.py` per-test isolation | PARTIAL | E-EF-024, E-EF-025 |
| E-03 | Coverage with meaning: ≥ 85 % line / ≥ 75 % branch overall; ≥ 95 % branch on auth, authorization, tenancy, scoring, retention, RAG abstention/citation | `ci.yml` job `api` coverage step (`--cov=bangla_gpt_api --cov-branch`, `fail_under=80` in `apps/api/pyproject.toml`); critical-module set measured by `.audit/evidence/E-R2-e2-001-*` (before) and `E-R2-e2-002-*` (after); new tests in `apps/api/tests/test_e2_coverage_gaps.py`, `test_e2_factories.py` | VERIFIED for the measured set | E-R2-e2-001/002 |
| E-04 | Mutation testing on critical modules, score ≥ 70 %, survivors triaged | `.audit/tmp/e2-mutations.txt` + `.audit/tmp/e2-mutation.sh` (20-test sample, see E-05); mutmut config and bounded run: `.audit/evidence/E-R2-e2-004-*`; nightly wiring: `.audit/handoffs/workflows-e2.md` | PARTIAL (sampler + one module nightly; no full-suite mutation gate) | E-R2-e2-004 |
| E-05 | 20 sampled tests each fail when the code under test is broken | `.audit/tmp/e2-mutations.txt`, run log `.audit/evidence/E-R2-e2-003-*`; three survivors from the audit's earlier sample are now pinned by added cases in `test_adaptive.py` (`test_e2_expected_score_pins_the_400_point_scale`, `test_e2_item_elo_moves_opposite_to_the_student`) and `test_kg.py` (`test_e2_weak_prerequisite_direction_is_pinned`) | VERIFIED | E-R2-e2-003 |
| E-06 | API contract tests with negative cases and a backward-compatibility check | `apps/api/tests/test_openapi_contract.py`, `test_openapi_auth_matrix.py`, `test_cd_error_contract.py`; reference drift via `apps/api/scripts/gen_api_docs.py --check` (`ci.yml` job `api`) | PARTIAL (no schemathesis fuzzing, no previous-release spec diff) | E-EF-020 |
| E-07 | Postgres 16: migration up/down/up with seeded data; constraints and indexes asserted | `ci.yml` job `postgres` (`alembic upgrade head` → `alembic check` → `downgrade` → `upgrade`, then `pytest tests/test_postgres_smoke.py -v` and the full domain suite); `apps/api/tests/test_school_model.py` (seeded backfill), `test_migrations_match_models.py` | VERIFIED | E-EF-010b, E-EF-033 |
| E-08 | Authorization and tenancy negative suite runs in CI | `apps/api/tests/test_school_tenancy_isolation.py` (two schools, cross-tenant reads and crafted ids refused), `test_school_routes_coverage.py`, `test_school_admin_edges.py`, `test_openapi_auth_matrix.py`; all run inside the `api` and `postgres` jobs | VERIFIED | E-EF-020 |
| E-09 | Frontend tests: components, hooks, i18n completeness, API mocks aligned with OpenAPI | vitest suite in `apps/web/src/**/*.test.tsx`; i18n parity gate `scripts/check_i18n.py` (`ci.yml` job `guardrails`); eslint/prettier/tsc in job `web` | PARTIAL (no check that mocked API shapes match the OpenAPI document) | E-EF-020, E-EF-016 |
| E-10 | Playwright e2e for the five roles on Chromium in CI, other engines nightly, traces on failure | `apps/web/e2e/smoke.spec.ts` in `ci.yml` job `e2e-smoke`; `.github/workflows/nightly.yml` job `e2e-nightly` runs every project `apps/web/playwright.config.ts` defines and uploads traces/junit/HTML | PARTIAL (WebKit/Firefox projects are not defined in the Playwright config yet) | E-EF-020, E-R2-e2-004 |
| E-11 | Property-based or fuzz tests for normalization, CSV import, stemmer, chunker, citation parser | `apps/api/tests/test_e2_property_based.py` (hypothesis; normalizer, hybrid tokenizer/stemmer/trigram, chunker packing/dedupe, `verify_citation`) | VERIFIED | E-R2-e2-005 |
| E-12 | Automated accessibility on every route + manual keyboard/screen-reader checklist | `apps/web/src/test/axeSweep.test.tsx`, `axeWelcome.test.tsx`; Playwright `apps/web/e2e/axe.spec.ts`, `keyboard.spec.ts`, `screen-reader.spec.ts`; Lighthouse budgets in `nightly.yml` job `lighthouse` | PARTIAL (route coverage and the manual pass are incomplete) | E-EF-020, E-EF-026 |
| E-13 | Visual regression across theme, locale and viewport with reviewed baselines | `apps/web/e2e/visual.spec.ts` exists as a scaffold; no committed baselines and no CI job | GAP (owner: web/e2e work) | E-EF-020 |
| E-14 | Performance/load tests with thresholds, scheduled, results archived | `load/` k6 scripts, `apps/api/scripts/bench_dashboards.py`, `docs/scale_report.md`, `docs/capacity_plan.md`; not scheduled in CI | PARTIAL (manual only) | E-EF-020, E-EF-026 |
| E-15 | Fault injection for LLM, DB and SMTP outages with graceful degradation | `apps/api/tests/test_e2_fault_injection.py` (dead DB via a refusing engine: `/ready` 503, `/status` degraded, coded 500 with request id and no DSN leak; dead SMTP via a real refused connection: `send_mail` False, registration/reset still complete; LLM 429/timeout/malformed through the real `GeminiProvider` on `httpx.MockTransport` → 502 `llm_unavailable`); provider suites `test_providers_gemini.py`, `test_providers_openai.py`, `test_circuit_breaker.py` | VERIFIED | E-R2-e2-006 |
| E-16 | Factories/fixtures with Bangla-realistic data, no real PII, injectable clock | `apps/api/tests/factories.py`, `apps/api/tests/test_e2_factories.py` (NFC/Bangla-block vocabulary checks, corpus-verbatim sentence, tenancy factories); clock seam `apps/api/src/bangla_gpt_api/db/clock.py` + `apps/api/tests/conftest_clock.py` (`FixedClock.installed()` / `.patched()`) | VERIFIED | E-R2-e2-007 |
| E-17 | Zero known flaky tests; quarantine with owner and date; no retries-as-fix | Seeded random-order runs (E-EF-024/025); `ci.yml` configures no retries; the intermittent docker-smoke failure has its own finding (AUD-EF-01) with a fix and a regression test `test_ef_sqlite_boot.py` | PARTIAL (no formal quarantine list artefact) | E-EF-024, E-EF-048 |
| E-18 | Docker image and production-like compose smoke | `ci.yml` docker job (build, run, `/health`, `/ready`); `docker-compose.yml` stack scripts under `scripts/` | PARTIAL (the compose stack is not smoked in CI) | E-EF-016 |
| E-19 | The RAG evaluation suite is treated as a test suite with gates | `ci.yml` job `golden-eval` (`apps/api/scripts/evaluate_golden.py`, then `python -m bangla_gpt_api.evaluation.cli` against `apps/api/eval/baseline_v2.json` over the 646-item frozen golden set, then `--redteam` over the 43 adversarial prompts); `.github/workflows/eval-gate.yml` fails on a > 2 percentage-point regression; `nightly.yml` job `live-eval` records the BLOCKED state when no provider key exists | VERIFIED (deterministic gates); live-model run BLOCKED | E-R2-e2-008, E-EF-016 |
| E-20 | Test strategy document (ISO/IEC/IEEE 29119 concepts) + requirement-to-test matrix | `docs/testing-strategy.md` (this matrix's companion) and `docs/requirements-traceability.md` | VERIFIED | E-R2-e2-009 |

## 2. Cross-domain items whose evidence is a test

| Item | Requirement (abridged) | Test artifact / gate | Status |
|---|---|---|---|
| A8 RAG evaluation | Held-out golden split, regression gate, red-team suite | `bangla_gpt_api.evaluation.cli` (`--split test`, `--redteam`), `apps/api/eval/golden_v2.json` (646 items, frozen), `redteam_v2.json` (43 cases), `apps/api/tests/test_a2_golden_construction.py`, `test_a2_redteam_suite.py`, `test_eval_v2.py` | VERIFIED |
| A4 grounding/abstention | Citation verification and numeric contradiction abstain; refusal reasons surfaced | `apps/api/tests/test_rag_v2.py`, `test_rag_runtime.py`, `test_a2_numeric_check.py`, `test_injection_guard.py`; property tests for `verify_citation` in `test_e2_property_based.py` | VERIFIED |
| B-07 / B-08 authorization and tenancy | Cross-role and cross-tenant access refused; role matrix pinned | `apps/api/tests/test_school_tenancy_isolation.py`, `test_openapi_auth_matrix.py`, `test_phase1_exploits.py`, `test_round2_auth_hardening.py` | VERIFIED |
| B-01/B-02 auth hardening | Argon2id hashing, single-use tokens, login lockout, logout revocation | `apps/api/tests/test_password_hashing.py`, `test_single_use_tokens.py`, `test_login_lockout.py`, `test_b_security_headers.py` | VERIFIED |
| B-28/B-29 privacy | Data export completeness; deletion cascades; PII scrubbing | `apps/api/tests/test_data_export.py`, `test_export_completeness.py`, `test_account_deletion.py`, `test_delete_cascade_v2.py`, `test_pii.py` | VERIFIED |
| G-* Bangla/UI quality | Bangla text hygiene, i18n parity, glossary | `apps/api/tests/test_bangla_matrix.py`, `scripts/check_glossary.py`, `scripts/bn_scan.py`, `scripts/check_i18n.py` | VERIFIED |
| H-14 clock seam | Time-dependent code reads an injectable clock | `apps/api/src/bangla_gpt_api/db/clock.py`; used by `services/retention.py`, `services/mailer.py`, `services/parent_digest.py`; verified by `test_e2_factories.py::test_retention_cutoff_follows_the_injected_clock` | VERIFIED |
| I-03 observability | Fault paths produce structured logs/traces | `apps/api/tests/test_hi_observability.py`, `test_request_context.py`, `test_health_observability.py` | VERIFIED |

## 3. Explicit gaps

| Catalog item | What is missing | Owner / next step |
|---|---|---|
| E-06 | schemathesis-style fuzzing; backward-compatibility diff against the previous release spec | needs `schemathesis` in the dev extra (see `.audit/handoffs/pyproject-e2.md`) then a CI job |
| E-13 | Visual-regression baselines and a CI job | web/e2e work |
| E-14 | Scheduled load run with archived results | CI owner (`.github/**` is not owned by the Domain-E subagent) |
| E-10 (residual) | WebKit/Firefox projects absent from `apps/web/playwright.config.ts` (the nightly job detects and skips them) | web/e2e work |
| E-12 (residual) | Every-route axe sweep in a real browser; manual keyboard/SR checklist | frontend + QA |
| E-17 (residual) | A quarantine list artifact with owner and date per entry | QA |
| E-19 (residual) | Live-model evaluation (BLOCKED: no provider key) | owner-provided key |

## 4. How to reproduce the measurements in this matrix

```bash
# API suite (hermetic SQLite)
cd apps/api && ../../.venv/Scripts/python.exe -m pytest -q

# Coverage, including the critical-module set
cd apps/api && ../../.venv/Scripts/python.exe -m pytest -q \
  --cov=bangla_gpt_api.auth.single_use --cov=bangla_gpt_api.ratelimit \
  --cov=bangla_gpt_api.security --cov=bangla_gpt_api.routers.tutor \
  --cov=bangla_gpt_api.services.quiz --cov=bangla_gpt_api.services.retention \
  --cov=bangla_gpt_api.routers.auth --cov=bangla_gpt_api.routers.school \
  --cov-branch --cov-report=term-missing

# Test-quality mutation sample (scratch copy only; never touches tracked files)
bash .audit/tmp/e2-mutation.sh .audit/tmp/e2-mutations.txt

# Evaluation gates
cd apps/api && python -m bangla_gpt_api.evaluation.cli --split test
cd apps/api && python -m bangla_gpt_api.evaluation.cli --redteam
```

Numbers in `.audit/evidence/` carry the timestamp, git SHA and exit code of the
run that produced them; this matrix cites those IDs rather than restating values
that will drift.
