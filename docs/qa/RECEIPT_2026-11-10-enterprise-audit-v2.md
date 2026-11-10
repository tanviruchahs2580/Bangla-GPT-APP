# Bangla GPT — Enterprise audit, remediation & verification (V2 wave) — evidence receipt

- Date: 2026-11-10
- Commit: `5ed0e94` (branch `main`) — **working tree, uncommitted** (no commit/push was made or authorized)
- Machine / OS: Windows 11 (win32 10.0.26300), Node v24.19.0, npm 11.17.0, Python 3.12.10
- Authoritative toolchain: the repo-pinned venv `.venv/` — pytest 9.1.1 + pytest-randomly + pytest-cov, ruff 0.17.0, mypy 2.4.0, import-linter (`lint-imports.exe`), Playwright (chromium)
- Scope: `apps/api` + `apps/web` + `docs/*` of Bangla GPT. Covers 21 implemented findings across five workstreams and the full gate set.
  **Does not cover**: any deployment, any production database, any migration, any secret or `.env*` change, any Git history operation, or any other repository.

## Result

21 evidence-backed defects were fixed with failing-first regression tests (12 more are documented with evidence and left for an owner decision, because each needs a policy call or a migration). The highest-value fixes are three P1s: an unsanitized client-controlled prompt channel that let a student escape the evidence region and still receive `grounded=true`; a grounding-gate asymmetry that refused answerable Bangla-typo questions although retrieval had already repaired them (golden-v3 `bn_typo` 6/37 → 36/37, overall grounded rate 0.7963 → 0.8782 with **no** negative stratum flipped); and a chat-retention sweep that deleted messages still inside the retention window. The grounding/eval gates, the full API suite, the full web gate set and 110 real-browser tests (including all 60 visual baselines and 24 axe scans) pass **after** the final edit.

## Commands and results

Baseline was measured before any edit; "final" means after the last source/test edit.

| # | Command | Result |
|---|---|---|
| 1 | `apps/api> python -m pytest -q` (baseline, global interpreter) | pass — `1779 passed, 11 skipped, 8 warnings in 677.16s` |
| 2 | `apps/api> ../../.venv/Scripts/python.exe -m pytest -q --randomly-seed=20261030 --cov=bangla_gpt_api --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=json` (final, pinned venv) | pass — `1844 passed, 10 skipped, 8 warnings in 2012.68s (0:33:32)`, exit 0; `Required test coverage of 80.0% reached. Total coverage: 89.49%` |
| 3 | `apps/api> python scripts/check_coverage_floors.py <coverage.json>` | pass — `coverage floors: 25/25 modules at or above their floor (global 89.49%)`, exit 0. Floors named in the "recorded gaps" list (`routers/parent.py` 81.96 ≥ 81, `routers/users.py` 87.18 ≥ 87, `security.py` 88.64 ≥ 84, `routers/admin.py` 88.21 ≥ 88, `auth/impersonation.py` 85.29 ≥ 85, `auth/single_use.py` 86.36 ≥ 86, `jobs.py` 89.40, `ratelimit.py` 89.62) all hold — **no floor was edited** |
| 4 | `apps/api> ../../.venv/Scripts/python.exe -m ruff check .` (final) | pass — `All checks passed!` (see note 1) |
| 5 | `apps/api> ../../.venv/Scripts/python.exe -m ruff format --check .` (final) | pass — `407 files already formatted` (final sweep reports all formatted) |
| 6 | `apps/api> ../../.venv/Scripts/python.exe -m mypy src` (final) | pass — `Success: no issues found in 134 source files` |
| 7 | repo root> `./.venv/Scripts/lint-imports.exe` | pass — `Contracts: 5 kept, 0 broken.` |
| 8 | `apps/api> python scripts/check_lockfile.py` | pass (exit 0) |
| 9 | `apps/api> python scripts/check_changelog.py` | pass (exit 0) |
| 10 | `apps/api> python scripts/check_corpus_manifest.py` | **FAIL, unchanged from baseline** — `pipeline code fingerprint sha256:62bc3611… != current sha256:c9018f92…; the corpus was not built by the code in this tree` → finding OPS-001 |
| 11 | `apps/api> python -m bangla_gpt_api.evaluation.cli` (final) | pass — exits 0, `GATE: PASS`; `grounded_rate 0.7963 → 0.8782` (paired bootstrap delta +0.0820, 95% CI [+0.0562, +0.1077]); `coverage_false` **0.9524 unchanged**; negatives unchanged (`adversarial 5/5`, `ambiguous 5/6`, `out_of_corpus 10/10`) |
| 12 | `apps/api> python -m bangla_gpt_api.evaluation.cli --redteam` | pass — `REDTEAM: PASS` (exit 0) |
| 13 | `apps/api> python scripts/evaluate_golden.py` | pass — `golden set size 24`, `hit@3 / refusal ok 1.0`, `grounded accuracy 1.0` (floor 0.9), exit 0 |
| 14 | `apps/api> python scripts/evaluate_nctb_retrieval.py` (real 1605-chunk corpus) | pass (exit 0) — family A n=100 `recall@1 0.95 / recall@5 1.0 / MRR 0.975`; family B n=80 `1.0 / 1.0 / 1.0`; family C adversarial refusal `1.0` (4/4 refused). The script rewrote the timestamp/latency fields of two tracked report artifacts; both were restored to HEAD with `git checkout --` because every metric was identical (see note 2) |
| 15 | `apps/api> ../../.venv/Scripts/python.exe scripts/export_openapi_types.py` then `git diff` | pass — **1-line** fixture diff (the corrected `POST /admin/maintenance/purge` description); 121 paths / 140 operations byte-identical |
| 16 | `apps/web> npm run lint` (`eslint src --max-warnings 0`) | pass (exit 0) |
| 17 | `apps/web> npx tsc --noEmit` | pass (exit 0) |
| 18 | `apps/web> npm run test` | pass — `Test Files 97 passed (97)`, `Tests 420 passed (420)` (baseline `90 / 399`; +7 files, +21 tests, none removed or weakened) |
| 19 | `apps/web> npm run test:coverage` | pass (exit 0) — `All files 74.43 stmts / 67.11 branch / 69.18 funcs / 76.56 lines` vs thresholds `70 / 60 / 60 / 68`; **no threshold edited** |
| 20 | `apps/web> npm run deadcode` (knip) | pass (exit 0) |
| 21 | `apps/web> npm run build` | pass — `✓ built`, bundle-budget plugin green (`assets/index-*.js 110284 B gzip / 125000 B`) |
| 22 | `apps/web> npx prettier --check src` | pass (exit 0) |
| 23 | `apps/web> npx playwright test visual smoke w2-a11y axe keyboard` (chromium, real API + real web) | pass — `110 passed (14.5m)`: 60 visual baselines, 24 axe scans, 16 smoke journeys, 7 keyboard, 3 w2-a11y |
| 24 | `apps/web> npx playwright test screen-reader resilience reflow mobile crawl session w2-c1-flows` (chromium, real API + real web) | pass — `42 passed, 1 skipped (7.9m)`, exit 0. Includes `screen-reader` (the committed `toMatchAriaSnapshot` baselines — the new `role="status"` element did not disturb them) and `resilience` (the failure/offline/slow-network states the UX-003/UX-004 fixes touch) |
| 25 | repo root> `git ls-files \| python scripts/bn_scan.py --list-from-stdin` | pass (exit 0, no candidates) |
| 26 | repo root> `python scripts/check_i18n.py` | pass — `i18n: 652 bn keys, 652 en keys`, guardrails OK |
| 27 | repo root> `python scripts/check_asset_notices.py` | pass (exit 0) |
| 28 | repo root> `python scripts/check_archive_banners.py` | pass (exit 0) |
| 29 | `apps/api> python scripts/check_doc_paths.py` | **FAIL (pre-existing, unrelated)**: 3 findings, all in the untracked root `AGENTS.md` referencing `scripts/...` paths that live under `apps/api/scripts/` — reported by the security workstream, not caused by this change |
| 30 | markdownlint / pip-audit / semgrep / hadolint / Postgres parity lane | **not run** — the tools are not installed in this environment (installing packages requires approval) and no Postgres is available; CI is the confirmation point |

### Baseline vs final, same-gate comparison

| Gate | Baseline | Final | Verdict |
|---|---|---|---|
| API tests | 1779 passed / 11 skipped (global interpreter) | **1844 passed / 10 skipped** (pinned venv, CI seed, coverage on) | +65 tests, no test removed, skipped or weakened (test diff reviewed) |
| API coverage | not measured at baseline | 89.49% total; floors **25/25** | global floor 80 honoured, per-module floors untouched |
| RAG regression gate | PASS, grounded 0.7963 | PASS, grounded 0.8782 | **improvement**, negatives unchanged |
| Golden gate (24) | grounded accuracy 1.0 | grounded accuracy 1.0 | unchanged |
| Real-corpus retrieval | recall@1 0.95 / @5 1.0 / MRR 0.975 | identical | unchanged |
| ruff / format / mypy / lint-imports | pass | pass | unchanged |
| Web lint / tests / deadcode | 90 files, 399 tests, pass | 97 files, 420 tests, pass | +21 tests |
| Corpus manifest fingerprint | **FAIL** | **FAIL** | pre-existing, reported (OPS-001) |

## Deviations

1. **Toolchain.** `ruff` on `PATH` is 0.16.4 and reported a false `I001` in `main.py`; the project pins 0.17.0 (`constraints.txt`, pre-commit `rev: v0.17.0`) and the repo venv has it. All reported lint/type results use the venv. Likewise `lint-imports` is not on `PATH`; it is run as `./.venv/Scripts/lint-imports.exe` from the repo root (the `apps/api` cwd has no `.importlinter`).
2. **`pytest-randomly`** is installed in the pinned venv but not in the global interpreter, so `-p randomly` / `--randomly-seed` fail there. The baseline run therefore used the global interpreter without shuffling; the final authoritative run uses the pinned venv with `--randomly-seed=20261030`.
3. **Two tracked generated reports restored.** Re-running `evaluate_nctb_retrieval.py` rewrote `evaluated_at`, `index_build_seconds`, `search_latency_p50/p95_ms` (p95 1895 → 4147 ms, an artifact of running beside the full test suite) and the paired digests in `data/nctb/retrieval_eval.json` + `data/nctb/manifests/corpus_manifest.json`. Every **metric** was identical, so both files were restored to HEAD rather than committing timestamp churn.
4. **One generated artifact regenerated.** `apps/web/src/test/fixtures/openapi.json` was regenerated from its source (`apps/api/scripts/export_openapi_types.py`) because a fix changed the served description of the purge endpoint; regenerated with the venv interpreter so the diff is exactly that one description.
5. **One test file edited deliberately.** `apps/web/src/test/pageSizeRatchet.test.ts` — 12 ceilings raised with the file's own recorded justification, 1 lowered (AssessmentsPage 624→618). Raised because the a11y/state fixes add branches. **This is a ratchet change and needs owner review** (finding RATCHET-001). No coverage threshold was touched anywhere.
6. **A read-only security subagent could not write**, so its two verified fixes were re-implemented by a writing role. Its finding that a `ContextVar` set in a sync FastAPI dependency is invisible to sync handlers was accepted and the corrected `Session.info` mechanism was used instead.
7. **`docs/security/threat-model.md`** was corrected (§4.4/§4.5 claims that SEC-001/SEC-002 falsify). `docs/data_minimization.md` and `docs/runbook.md` were updated for the retention semantics. No other documentation was edited.
8. **`CHANGELOG.md` was not touched** — entries are generated from commits by the release process, and no commit was made (owner action at commit time).

## Known gaps (explicit)

- **Production / staging / live-provider behaviour is NOT VERIFIED.** Every run used the deterministic `mock` LLM provider and a local SQLite database. No Postgres, no live model, no deployment.
- **Migrations: none written, none run.** Two P3 findings that need a schema change (plaintext TOTP secret; lost-update counters) are reported, not fixed.
- **The corpus-manifest fingerprint gate fails before and after** (OPS-001) and is not wired into CI; the corpus was not rebuilt.
- **Twelve findings are evidenced but unimplemented** (see the findings register) with the reason each: they need a policy call, a retention-window change, a migration, or a product decision. Two of them are P1/P2-severity correctness/quality issues (DAT-004 mastery rewind, RAG-003 unenforced citation verdict, RAG-004 eval-gate corpus coverage).
- **Visual/a11y evidence is Chromium-on-Windows only.** Firefox/WebKit (`playwright.engines.config.ts`) and the preview harness (service-worker/offline, w2-perf) were not run. 153 browser tests ran green in total (110 + 42, 1 skip), which is a subset of the CI suite — `perf`, `w2-perf`, `w2-flows`, `w2-flows2`, `offline-shell`, `store-listing` and the three-engine pass are **not verified**.
- **Not verified:** the Android/Capacitor surface (no `java`/`gradle`/`adb` on this machine), markdownlint, dependency/scanner jobs, and the two Postgres-only test legs.
