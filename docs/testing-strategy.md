# Testing strategy

Status: living document. Owner: QA / release engineering. Audience: contributors,
reviewers and the release owner.

This document states how Bangla GPT is tested: the levels, the environments, the
data rules, the entry and exit criteria, and what happens when a test fails. It is
organised after the ISO/IEC/IEEE 29119 concepts (test levels, test process, entry
and exit criteria, incident management) without claiming conformance to that
standard's documentation set.

Companion documents:

- `docs/requirements-traceability.md` — requirement (catalog ID) to test mapping.
- `docs/qa/QA_REPORT_2026-10-17.md` — a point-in-time report, not this strategy.
- `.audit/reports/FINAL.md` — the audit's findings and their status.

---

## 1. Scope

**In scope.** Everything the repository builds and runs: the FastAPI service
(`apps/api`), the React PWA (`apps/web`), the evaluation harness
(`apps/api/src/bangla_gpt_api/evaluation`, `apps/api/eval`), the NCTB corpus
pipeline (`apps/api/src/bangla_gpt_api/nctb`), the container/compose stack
(`Dockerfile`, `docker-compose.yml`), and the CI workflows that exercise them.

**Out of scope.** Production infrastructure and credentials; real user data;
paid third-party spend beyond the audited cap; linguistic certification of Bangla
output (we produce review sheets, not certifications); legal or licensing
conclusions.

**Product constraints that shape testing.** Bangla-first and curriculum-grounded;
the users are minors; the deployment target includes low-bandwidth, low-end
devices. That is why the retrieval/abstention behaviour, the child-safety
screening and the Bangla text handling are tested at more levels than a generic
CRUD service would be.

## 2. Test levels

| Level | What it proves | Where it lives | Runtime budget |
|---|---|---|---|
| Unit | Pure logic and module contracts (Elo math, chunk packing, PII scrubbing, retention cutoffs, tokenizer/normalizer invariants) | `apps/api/tests/`, `apps/web/src/**/*.test.tsx` (vitest) | minutes, no network, no external service |
| Integration (API) | Routes through the real app: auth, authorization, tenancy, DB writes, error contract | `apps/api/tests/` with `TestClient(create_app(...))` on a hermetic SQLite database, plus the Postgres leg | ≤ 10 min for the affected slice |
| Contract | OpenAPI ↔ implementation: documented status codes, no undeclared public operation, API-reference drift | `apps/api/tests/test_openapi_contract.py`, `test_openapi_auth_matrix.py`, `apps/api/scripts/gen_api_docs.py --check` | < 1 min |
| Database | Migrations up → check → down → up; seeded-data reversibility; model/migration drift | `apps/api/tests/test_migrations_match_models.py`, `test_school_model.py`, CI `postgres` job on PostgreSQL 16 | ≤ 10 min |
| End-to-end (browser) | The five roles' critical journeys in a real browser against a real API | `apps/web/e2e/` (Playwright): `smoke.spec.ts` on PRs; the full project matrix nightly | smoke ≤ 10 min |
| Evaluation (RAG) | Retrieval quality, abstention and safety on a frozen golden set | `bangla_gpt_api.evaluation.cli`, `apps/api/scripts/evaluate_golden.py`, `.github/workflows/eval-gate.yml` | ≤ 15 min |
| Property-based | Invariants over generated inputs for parsers/normalizers | `apps/api/tests/test_e2_property_based.py` (hypothesis) | < 2 min |
| Fault injection | Graceful degradation for LLM, DB and SMTP outages | `apps/api/tests/test_e2_fault_injection.py`, provider suites (`test_providers_*.py`), `test_circuit_breaker.py` | < 3 min |
| Performance / load | Latency and throughput budgets, dashboard queries at scale | `load/`, `apps/api/scripts/bench_dashboards.py`, `docs/capacity_plan.md` | manual/scheduled (see §8) |

Tests are written to the arrange-act-assert shape, assert observable behaviour
(status codes, response bodies, rows read back from the database, emitted logs),
and avoid logic of their own ("no logic in tests"). Snapshot-style assertions are
not used as a substitute for behavioural ones.

## 3. Environments and test data

**API default (hermetic).** `apps/api/tests/conftest.py` forces `_env_file=None` and
an in-memory SQLite database, so no developer `.env` or on-disk database is ever
touched. Env-var leakage between tests is prevented by scrubbing every `Settings`
field's environment variable per test.

**PostgreSQL 16.** `BGPT_TEST_DATABASE_URL` (or `TEST_DATABASE_URL`) switches the
same suite onto a real Postgres, with `TRUNCATE ... RESTART IDENTITY CASCADE`
between tests. The CI `postgres` job runs migrations plus the full domain suite on
that engine; SQLite-only behaviour (for example its serialisation of concurrent
writers) is therefore never mistaken for product behaviour.

**Redis.** Cache and shared-rate-limit behaviour is exercised against a real Redis
in the `api` job (T-016 step) and conditionally in `test_cache_v2.py`;
`RATE_LIMIT_BACKEND=redis` has its own backend tests with a fake client for the
failure paths.

**Browser.** Chromium on every pull request (`e2e-smoke`); the full Playwright
project matrix on the nightly schedule, with traces and the HTML report uploaded
on failure.

**Test data.** Newer suites build rows through `apps/api/tests/factories.py`:
Bangla-realistic names, conjunct-heavy sentences and Bengali digits, unique
emails/codes by default so the same factory works against the persistent Postgres
database. No real personal data is used anywhere; the only "phone numbers" in
tests are non-routable fixtures in the shape the PII scrubber recognises. The
factory sample sentence is asserted to be a verbatim substring of the shipped
sample corpus, so test prose cannot drift from the product's own text
(`apps/api/tests/test_e2_factories.py::test_sample_sentence_is_verbatim_corpus_prose`).

**Clock.** Time-dependent code reads the seam
`bangla_gpt_api.db.clock` (`utcnow()` / `Clock` / `set_clock`). Tests install
`conftest_clock.FixedClock` through `FixedClock.installed()` — or, for modules not
yet migrated, patch that module's `datetime` with `FixedClock.patched(module)`.
No test sleeps to cross a boundary.

## 4. Entry criteria

Before a level is considered runnable, or before a change is handed to review:

1. The tree imports and the affected test files are green locally.
2. New behaviour has a test that fails without the change (state in the test
   docstring what mutation of the code under test makes it fail).
3. No new suppression, skip or `xfail` without a reason string and an issue
   reference in the same commit.
4. Static gates pass for the touched language (`ruff check`, `ruff format
   --check`, `mypy`; `eslint`, `prettier`, `tsc`) — G1 in the audit's gate table.

## 5. Exit criteria (what makes a change releasable)

| Gate | Threshold | Enforced by |
|---|---|---|
| API suite | all green, 0 failures, on Python 3.11 and 3.12 | `ci.yml` job `api` |
| Coverage | `fail_under = 80` (branch-aware, from `apps/api/pyproject.toml`); the critical-module target is ≥ 95 % branch on auth, single-use tokens, rate limiting, retention, quiz scoring, tutor routes, the auth router and school tenancy | `ci.yml` job `api` (coverage step) + `.audit/evidence/E-R2-e2-*` for the critical set |
| Mutation sample | ≥ 70 % of the sampled mutants killed on the selected critical module (mutmut, bounded) | nightly (see `.audit/handoffs/workflows-e2.md`) |
| Postgres | migration cycle + `alembic check` + domain suite green | `ci.yml` job `postgres` |
| Evaluation | golden-set metrics within 2 percentage points of the recorded baseline; red-team prompts all refuse with no leak markers | `ci.yml` job `golden-eval`, `.github/workflows/eval-gate.yml` |
| Web | `npm ci`, eslint `--max-warnings 0`, prettier, `tsc` + `vite build`, vitest (`npm test`) all green; i18n key parity via `scripts/check_i18n.py` | `ci.yml` job `web`, `guardrails` |
| E2E | Chromium smoke journeys pass against a real API | `ci.yml` job `e2e-smoke` |
| Accessibility | axe sweep green for the covered routes; Lighthouse accessibility budget 1.00 on public routes (nightly) | vitest axe suites; `nightly.yml` job `lighthouse` |
| Security | secret scan, dependency audit, SAST, container/SCA screens green or covered by a dated, justified suppression | `ci.yml` security steps, `codeql.yml`, `nightly.yml` |
| Docker | image builds, container answers `/health` and `/ready` | `ci.yml` docker job |

A red gate blocks the merge; it is fixed, not retried into green. Thresholds are
only changed in a commit that states the measured reason (see
`.audit/findings-ef.csv` and the suppression register in the final report).

## 6. Defect workflow and severity

1. **Record.** Every finding gets a row in `.audit/findings-*.csv` with an ID, a
   severity, evidence IDs, a status and a note; evidence is captured under
   `.audit/evidence/` by `.audit/ev.sh` (timestamp, git SHA, command, exit code).
2. **Severity.**
   - **S0** — data loss/corruption, a live secret, a cross-tenant or cross-role
     data exposure, or a child-safety failure. Stop; fix before anything else.
   - **S1** — a broken core journey, an authentication/authorization bypass, a
     gate that cannot fail, or a compliance obligation with a deadline.
   - **S2** — a real defect on a secondary path, a missing gate, or a test that
     cannot fail. Fix in the current pass.
   - **S3** — hygiene, documentation drift, or an item whose cost exceeds its
     current risk. Schedule with an owner.
3. **Root cause first.** Fix the cause, not the assertion. A test changed to match
   buggy behaviour is itself a finding (I2).
4. **Verify differently.** Confirm a fix with a different method than the one that
   found it, and capture the before/after measurement (T12).
5. **Quarantine.** A flaky test is quarantined only with an owner, a date and an
   issue reference in the skip reason; CI retries never substitute for a fix.
6. **Exit.** A finding is closed only when its evidence ID points at a command
   that fails before the change and passes after it, or at a documented decision.

## 7. Traceability

`docs/requirements-traceability.md` maps each catalog item (`E-01` … `E-20`, plus
the test-bearing items of other domains such as `A8`, `B-07`, `B-08`, `G-*`) to
the test artifacts and CI jobs that satisfy it. When a test is renamed or moved,
that matrix is updated in the same commit — it is a checked artifact, not prose.

## 8. Known gaps (honest list)

These are open items in the finding register; they are listed here so nobody reads
this strategy as a claim that they are done.

| Gap | Catalog item | Note |
|---|---|---|
| No schemathesis-style API fuzzing and no backward-compatibility check against the previous release spec | E-06 | OpenAPI contract and auth-matrix tests exist inside the pytest suite; the fuzz/back-compat job does not |
| Visual regression is absent (no snapshot baselines for light/dark × bn/en × 360/768/1280) | E-13 | Deliberate: no baseline review process yet |
| Load tests are not scheduled and no per-release results are archived | E-14 | k6 scripts and `docs/scale_report.md` exist; the schedule does not |
| Accessibility automation covers a 9-page jsdom sweep with contrast excluded, and the manual keyboard/screen-reader pass is still open | E-12 | Needs a real-browser run and the manual checklist |
| Mutation testing is a bounded nightly sampler on one module, not a full-suite gate | E-04 | Score and module recorded in the nightly artifact |
| Order-dependence is verified with seeded random-order runs, not a parallelised matrix (`pytest-xdist` is not installed) | E-02 | Per-layer runtimes are not separately measured |
| Live-model evaluation is BLOCKED (no provider key) | E-19, A8 | The deterministic gates remain the enforced ones; `nightly.yml` records the BLOCKED state |

## 9. Changing this strategy

Changes to levels, thresholds or the data rules are made in a pull request that
(i) names the catalog item or finding it addresses, (ii) states the measured
before/after effect, and (iii) updates
`docs/requirements-traceability.md` in the same commit.
