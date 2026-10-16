# AUDIT EXECUTION LEDGER — Bangla GPT APP

Working ledger for the 2026-10-16 audit round. Updated as work proceeds so the
audit is resumable.

## Repository boundary

| Item | Value |
|---|---|
| Local root | `C:\Users\DST\projects\Bangla GPT APP` |
| Git root | same (verified `git rev-parse --show-toplevel`) |
| Branch | `main` |
| Baseline commit | `bbac9540c263cdd7b92d32ba05974e7665b3aec8` ("Full engineering audit + remediation: 47 findings fixed, 0 open (#1)") |
| Remotes | `origin` → https://github.com/tanviruchahs2580/Bangla-GPT-APP.git (fetch + push) |
| Working tree at start | DIRTY — 19 modified files, 1 staged rename, 24 untracked paths (see `AUDIT_SUMMARY.md` §Working-tree state) |
| Ownership note | The pre-existing uncommitted changes were treated as the owner's work in progress: nothing was reverted, stashed, or overwritten. This audit only added to them. |
| Remote writes | NONE. No commit, no push, no PR, no deploy, no repository/provider setting changed. |

## Phase log

| Phase | Status | Notes |
|---|---|---|
| 0 — Boundary + baseline | DONE | Baseline gates captured in `logs/baseline_*.log` (API 824 passed / 6 skipped; web 156 passed; ruff/mypy/eslint/build green; prettier 7 files) |
| 1 — Audit (checklist A–R) | DONE | Surface inventories + findings in `AUDIT_FINDINGS.md` (33 findings: 0 P0, 5 P1, 12 P2, 16 P3); per-item statuses in `AUDIT_TRACEABILITY_MATRIX.csv` |
| 2 — Rank + plan | DONE | P1 first; plan and rationale in `REMEDIATION_LOG.md` |
| 3 — Remediate | DONE | 9 findings fixed (F-01…F-08, F-25) in 8 change groups; every behaviour fix written test-first with the pre-fix failure observed |
| 3b — Live UI pass | DONE | 38 screenshots over 12 screens at 1366×768 and 390×844 against an isolated local stack; found F-25 (fixed) and F-26…F-33 (open) |
| 4 — Re-verify + second pass | DONE | `logs/final_api_gates.log` (828 passed / 6 skipped), `logs/final3_web_gates.log` (162 passed / 48 files, lint+build green); independent critic review in `AUDIT_SUMMARY.md` §Second-pass review |
| Deliverables | DONE | 10 reports + 2 matrices + probes + logs + screenshots in this directory |

## Commands executed (sanitized logs in `logs/`)

| Log | Command | Result |
|---|---|---|
| `baseline_api_gates.log` | `ruff check .` · `ruff format --check .` · `mypy src` · `pytest -q` (apps/api) | EXIT 0 / 0 / 0 / 0 — 824 passed, 6 skipped |
| `baseline_web_gates.log` | `npm run lint` · `vitest run --no-file-parallelism` · `npm run build` · `prettier --check src` | 0 / 0 / 0 — 156 passed; prettier EXIT 1 (7 files) |
| `baseline_guardrails.log` | `check_readme_contract.py` · `check_changelog.py` · `check_i18n.py` · `alembic heads` | readme EXIT 1 (fixed) · rest EXIT 0 |
| `probe_middleware_order.log` | `probe_middleware_order.py` (before fix) | CORS innermost; 429/413 carry no ACAO |
| `probe_preflight_budget.log` | `probe_preflight_budget.py` (before fix) | preflight consumed a login attempt |
| `probe_middleware_order.after.log` | same probe, after fix | CORS outermost; 429/413 carry ACAO |
| `api_dev_server.log` / `api_audit_server.log` / `web_dev_server.log` | local dev servers (port 8000 occupied by a pre-existing owner process — untouched; audit used port 8010 + an isolated SQLite DB) | API ready, provider `mock` |
| `final_api_gates.log` | same as baseline, post-fix | see `TEST_AND_CI_REPORT.md` |
| `final_web_gates.log` | same as baseline, post-fix | see `TEST_AND_CI_REPORT.md` |

## Baseline failures vs. regressions introduced

| Item | Class | Resolution |
|---|---|---|
| `check_readme_contract.py` EXIT 1 | **Pre-existing** failure in the owner's uncommitted work (staged rename of the QA record without updating the root README link) | FIXED here; re-run EXIT 0 |
| `prettier --check` 7 files | Pre-existing, not a CI gate | Reported STYLE-001, not reformatted (would add unrelated churn to the owner's in-progress files) |
| `alembic check` on the local dev SQLite file → "Target database is not up to date" | Environment artifact (stale local `bangla_gpt.db`), NOT a model/migration drift | Re-verified on a fresh DB: `alembic upgrade head` then `alembic check` → "No new upgrade operations detected" |
| No test/build/lint regression | — | Post-fix totals are ≥ baseline and all gates EXIT 0 |

## Decisions, assumptions, blockers

- **Assumption:** the pre-existing dirty working tree is the owner's in-progress work (it matches the open items in `docs/qa-audit-2026-10-14.md`). It was preserved verbatim.
- **Decision:** SEC-009 (cross-tenant `ChapterContent` reads) needs a product decision (add tenancy, or document shared content as intended) and a migration; not patched blindly.
- **Decision:** release-workflow hardening (`CI-REL-01`) is not patched here — it gates real releases and cannot be executed locally, so an untested change could break the release path. Reported with a concrete recommendation instead.
- **Blocker (authorization):** GitHub provider settings (branch protection, secret scanning, environment protection), production/staging observation, and Android release signing are outside the access available to this audit → `NOT VERIFIED`.
- **Blocker (tooling):** `gradle-wrapper.jar` + Android launcher assets are untracked in the owner's tree; committing them is an owner action (GIT-001).

## Exact stopping point

Audit complete for the locally verifiable scope. Verdict `NOT RELEASE-READY`
(NO-GO) with scope `PARTIALLY VERIFIED` (see `RELEASE_READINESS.md`). Open items
requiring owner decision or provider access: `F-09`, `F-10`, `F-12` (P1
blockers) plus the remaining P2/P3 items, and the `NOT VERIFIED` list in
`AUDIT_SUMMARY.md`.

## Process notes (for transparency)

- **One transient self-inflicted failure, disclosed rather than hidden:** an
  intermediate gate run (`logs/final2_web_gates.log`) shows `eslint EXIT=1` (18
  errors) because an incomplete refactor dropped a type import in
  `ParentDashboard.tsx`. It was fixed, and lint/tsc/tests/build were re-run green
  (`final3`). No rule was suppressed to clear it.
- A session token for the throwaway audit account was printed once in a tool
  call while setting up the live pass. It was signed with a local audit-only
  secret against a database that has since been deleted and grants access to
  nothing. No secret value appears in any report or log in this directory.
- The pre-existing dev server on port 8000 belongs to the owner and was left
  running and untouched; the audit used port 8010 and 5273 and stopped both.
