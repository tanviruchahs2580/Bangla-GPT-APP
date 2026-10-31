> **Historical, not current.** Kept for history only; this snapshot does
> not describe the current tree and must not be quoted as current status.
> Current sources of truth: [../README.md](../README.md).

# TEST & CI REPORT — Bangla GPT APP (2026-10-16)

All commands were executed in this working tree. Logs are in `logs/`. Where a
number appears below it was read from the tool's own output; nothing is
estimated.

## 1. Baseline (before any edit in this audit)

| Gate | Command | Exit | Result |
|---|---|---|---|
| API lint | `ruff check .` (apps/api) | 0 | All checks passed |
| API format | `ruff format --check .` | 0 | — |
| API types | `mypy src` | 0 | — |
| API tests | `pytest -q` | 0 | **824 passed, 6 skipped**, 1 warning (664.23s) |
| Web lint | `npm run lint` (`eslint src --max-warnings 0`) | 0 | — |
| Web tests | `npx vitest run --no-file-parallelism` | 0 | **156 passed** (47 files) |
| Web build | `npm run build` (`tsc && vite build`) | 0 | built in 18.63s |
| Web format | `npx prettier --check src` | **1** | 7 files — *not a CI gate* (`F-16`) |
| README contract | `python apps/api/scripts/check_readme_contract.py` | **1** | dead link (`F-01`, fixed here) |
| Changelog | `python apps/api/scripts/check_changelog.py` | 0 | "accounts for all 179 commits across 13 released versions" |
| i18n | `python scripts/check_i18n.py` | 0 | 580 bn / 580 en keys, parity 0, english-in-bn 0 (8 keys pending native review) |
| Migrations | `alembic heads` | 0 | single head `f2b3c4d5e6f7` |
| Migration drift | `alembic upgrade head` + `alembic check` on a **fresh** SQLite file | 0 | "No new upgrade operations detected" |

Baseline logs: `logs/baseline_api_gates.log`, `logs/baseline_web_gates.log`,
`logs/baseline_guardrails.log`.

**Baseline failure classification**

| Failure | Class | Evidence |
|---|---|---|
| `check_readme_contract.py` exit 1 | Pre-existing defect in the owner's in-progress rename | Fixed (R-01); re-run exit 0 |
| `prettier --check` 7 files | Pre-existing, and not wired into CI | Left as `F-16` |
| `alembic check` against the local dev `bangla_gpt.db` → "Target database is not up to date" | **Environment artifact, not drift** — that file predates the current head; CI runs the cycle on a fresh Postgres database | Re-run on a fresh DB: clean (`alembic check` → no new operations) |

## 2. Post-change verification

| Gate | Command | Exit | Result |
|---|---|---|---|
| API lint / format / types | `ruff check .` · `ruff format --check .` · `mypy src` | 0 · 0 · 0 | — |
| API tests | `pytest -q` | 0 | **828 passed, 6 skipped**, 1 warning (799.33s) |
| Web lint | `npm run lint` | 0 | — |
| Web tests | `vitest run --no-file-parallelism` | 0 | **162 passed** (48 files) — +6 vs baseline (see §4) |
| Web build | `npm run build` | 0 | built in 21.05s |
| Targeted new tests | `pytest tests/test_rate_limit_coverage.py tests/test_teacher_ai_budget.py -q` | 0 | 23 passed (these are the owner's newest untracked test files) |
| Targeted CORS suite | `pytest tests/test_cors.py tests/test_rate_limit_coverage.py tests/test_phase1_exploits.py tests/test_metrics_auth.py -q` | 0 | 30 passed |
| Targeted invite suite | `pytest tests/test_product_v3.py tests/test_remediation_characterization.py tests/test_wave2_api.py -q` | 0 | 41 passed |
| Migration drift re-check | fresh-DB `alembic upgrade head` + `alembic check` | 0 | no new operations |

The API suite grew by 4 (three CORS tests, one invite-entropy test); the web
suite grew by 6 across two files; a final re-run after the report-sentence fix
added a third file (`meReport.test.tsx`, 4 tests). Totals in §4.

## 3. Test quality review

**What is genuinely strong**

- **Authorization is tested as a matrix, not by sample.** `tests/test_openapi_auth_matrix.py` compares every OpenAPI operation against an explicit `PUBLIC_OPERATIONS` set, so a forgotten auth dependency fails the suite; `test_openapi_contract.py` requires 401/403 documented on every protected operation. Role/tenancy boundaries have dedicated tests (`test_auth_teacher.py`, `test_school_tenancy_isolation.py`, `test_admin_hardening.py`, `test_metrics_auth.py`, `test_phase1_exploits.py`).
- **The AI evaluation gate is real.** `eval-gate.yml` runs `python -m bangla_gpt_api.evaluation.cli`, which compares six metrics against the committed `eval/baseline_v2.json` (634 cases) and fails on a drop of more than 2 percentage points (`metrics.py::GATE_PP`). `test_eval_v2.py` covers the header/shape, the boundary, and a seeded-bad run.
- **Negative and adversarial cases exist**: injection guard (`test_injection_guard.py`), safety/refusal (`test_safety_v2.py`), red-team leak scan, provider failure → 502/503 (`test_tutor_api.py`), circuit breaker state machine (`test_circuit_breaker.py`).
- **Baseline upgrades were respected**: new tests were written to fail first (verified by patch-and-restore for the UI ones), and no existing test was weakened, skipped or loosened in this audit.

**Gaps worth closing (reported, not changed)**

1. `F-20` — the eval CLI exits 0 when `eval/baseline_v2.json` is missing, so the gate fails open if the baseline is absent or renamed.
2. Error-response coverage was thin: before this audit, the only CORS tests asserted 200/preflight behaviour, so nothing caught that rejections were unreadable cross-origin. The three added tests close that specific hole.
3. `F-14` — several UI states (failed search rendered as "no results", unpersisted toggle) have no test; the two silent-failure states that were fixed now do.
4. No unit tests for the retry/edit paths of the teacher generation UI beyond what exists; the live pass found genuine state bugs there.

## 4. Test counts (as printed by the tools)

| Suite | Baseline | Final | Delta |
|---|---|---|---|
| API (`pytest -q`) | 824 passed, 6 skipped | **828 passed, 6 skipped** | +4 |
| Web (`vitest run`) | 156 passed / 47 files | **162 passed / 48 files** | +6 |

The web total grew across three new/extended test files: `admincenter.test.tsx`
(+1), `workspace.test.tsx` (+1), and the new `meReport.test.tsx` (+4). Final
log: `logs/final3_web_gates.log` (eslint 0, vitest 0, build 0).

**One transient self-inflicted failure, disclosed.** An intermediate run
(`logs/final2_web_gates.log`) shows `eslint EXIT=1` with 18 errors in
`ParentDashboard.tsx`: while extracting `suggestionSentence` I dropped the
`ParentReport` type import that the file still used, so the type resolved to
`error`/`any` and the no-unsafe-* rules fired. The import was restored, and
`npm run lint`, `npx tsc --noEmit` and the full suite were re-run green
(`final3`). Nothing was suppressed or loosened to clear it — the gate caught a
real regression, which is the intended behaviour.

## 5. CI review (source-level only — no workflow was executed from here)

Four workflows exist: `ci.yml`, `eval-gate.yml`, `release.yml`,
`vercel-deploy.yml`. Logs of remote runs were **not** available, so every
statement below is a source-review statement, never an observed run.

**Verified good**

- Every third-party action in all four workflows is pinned to a full 40-char commit SHA; `persist-credentials: false` on checkouts.
- No `continue-on-error` anywhere; `|| true` appears only in cleanup/teardown or where the exit code is captured and asserted (`vercel-deploy.yml:73,81`).
- No `${{ ... }}` expression is interpolated into a `run:` shell block in any workflow (checked by grep) — no expression-injection surface; the release tag is passed through `env:`, not spliced into the script.
- `vercel-deploy.yml`'s `workflow_run` job is guarded by `conclusion == 'success'` **and** `event == 'push'` **and** `head_branch == 'main'` **and** `head_repository.full_name == github.repository`, and checks out `workflow_run.head_sha` — fork/PR code cannot reach it.
- Permissions are least-privilege: top-level `contents: read`; `contents/packages/attestations/id-token: write` only on the release build-push job that needs them; no `actions: write` anywhere.
- Dependency installs in `ci.yml` are hash-pinned (`--require-hashes -r constraints.txt`) with cache keys derived from that lockfile, so a poisoned cache entry cannot substitute a package.
- Gates are real: lint, format, types, tests with coverage, a Postgres upgrade→downgrade→upgrade cycle plus `alembic check`, `test_postgres_smoke.py`, the golden retrieval benchmark (fails below grounded accuracy 0.9), web audit/lint/vitest/build, README/changelog/i18n guardrails, gitleaks, and a Docker build + container smoke.

**Open CI findings** (detail in `AUDIT_FINDINGS.md`): `F-10` (tags run no CI and deploy by mutable tag rather than the recorded digest — the most consequential), `F-24` (production deploy gated on the API workflow only, not the eval gate), `F-22`, `F-23`, `F-21`, `F-20`.

## 6. What was NOT run (and why)

| Not run | Reason |
|---|---|
| `docker build` + container smoke | Docker is present locally but a full image build was not part of the audit budget; CI does it. `NOT RUN — not attempted`. |
| `pytest tests/test_postgres_smoke.py` | Needs a Postgres instance; the default local DB is SQLite. `NOT RUN — no Postgres service locally`. |
| `python -m bangla_gpt_api.evaluation.cli` (golden eval) | Hermetic but ~minutes of compute; CI covers it. `NOT RUN — time budget`. |
| `pip-audit` / `npm audit` | CI runs them; no local run. `NOT RUN`. |
| Android `gradlew assembleRelease` | Requires the Android SDK + the untracked wrapper/assets (`F-12`). `NOT RUN — toolchain and tracked files missing`. |
| Remote CI status, branch protection, environment protection | No GitHub API access from this environment. `NOT VERIFIED`. |
