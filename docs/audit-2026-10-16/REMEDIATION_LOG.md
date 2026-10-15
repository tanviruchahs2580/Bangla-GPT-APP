# REMEDIATION LOG — Bangla GPT APP (2026-10-16)

Ordered by the order the work was done. Every behaviour fix was written
test-first: the test was run against the unfixed code to confirm it fails, then
the fix was applied and the test re-run green. "Non-vacuous" below means that
first failure was actually observed, not assumed.

Scope discipline: no pre-existing uncommitted change was reverted, stashed or
reformatted. Each change is the smallest one that resolves the root cause.

---

## R-01 · README guardrail link (`F-01`, P1)

| | |
|---|---|
| Files | `README.md:60` |
| Root cause | The owner's staged rename of the QA record moved `docs/archive/qa-audit-2026-10-06.md` out of `docs/`, but the root README still linked the old path, so `apps/api/scripts/check_readme_contract.py` failed and the CI guardrails job would be red. |
| Change | The "Current QA record" line now points at `docs/qa-audit-2026-10-14.md` (matching `docs/README.md`'s "exactly one current record" rule) and links the archived record separately. |
| Evidence | Before: `::error::README links to a path that does not exist: docs/qa-audit-2026-10-06.md`, `EXIT=1`. After: "README endpoint table agrees with the metrics gate and CI install command.", `EXIT=0`. |

## R-02 · Middleware order: CORS outermost (`F-02`, `F-03`; P1 + P2)

| | |
|---|---|
| Files | `apps/api/src/bangla_gpt_api/initialize/middleware_stack.py`, `apps/api/tests/test_cors.py` |
| Root cause | `CORSMiddleware` was registered first, and Starlette's `add_middleware` prepends, so CORS resolved **innermost** — inside `RateLimitMiddleware` and `BodySizeLimitMiddleware`. Both short-circuit with a direct response, so their 429/413 never passed through CORS (no `Access-Control-Allow-Origin`) and preflights were counted by the limiter. The docstring asserted the opposite ("Order matters: 1. CORS … 6. Prometheus"), which is how the inversion went unnoticed. |
| Change | CORS is registered last (outermost). The docstring now documents the real Starlette semantics and states why CORS must stay outermost. No other middleware changed its relative position (body-size still runs before rate-limit; security headers and request-id still wrap both). |
| Tests (test-first) | 3 new tests in `tests/test_cors.py`. Before the fix: `3 failed, 4 passed` — the two CORS-on-rejection tests plus the preflight-budget test. After: `30 passed` (with `test_rate_limit_coverage.py`, `test_phase1_exploits.py`, `test_metrics_auth.py`). |
| Probes | `probes/probe_middleware_order.py` and `probes/probe_preflight_budget.py`, before/after logs in `logs/`. After: 429 and 413 carry `access-control-allow-origin`; runtime order begins with `CORSMiddleware`. |
| Deliberate consequence | Preflight responses are now answered by CORS before the request-id/security-header middlewares, so they carry CORS headers but no `X-Request-ID`/CSP. `docs/API.md` was updated to say so instead of claiming every response carries the header. |
| Risk review | Ordering relative to `ServerErrorMiddleware`/Sentry telemetry is unchanged (they are added by Starlette/Sentry, not here). Verified by printing the resolved stack, not by reading the source alone. |

## R-03 · Parent invite entropy (`F-04`, P2)

| | |
|---|---|
| Files | `apps/api/src/bangla_gpt_api/routers/parent.py:169`, `apps/api/tests/test_product_v3.py`, `apps/web/src/api.ts`, `apps/web/src/pages/ParentDashboard.tsx` |
| Root cause | `secrets.token_hex(4)` = 32 bits for a code that is the only secret protecting a parent link onto a child's record. |
| Change | `secrets.token_hex(8)` = 64 bits, with the reason recorded next to it. |
| Compatibility | Redemption looks codes up by SHA-256 hash (`_hash_invite`), and `ParentInviteLinkRequest.code` accepts 8–128 chars, so codes issued before the change still redeem. Verified by reading the schema and redemption path before changing the length. |
| Tests (test-first) | `test_product_v3.py::test_parent_invite_code_carries_enough_entropy` — failed pre-fix (`32 bits < 64`), passes post-fix. Whole file + `test_remediation_characterization.py` + `test_wave2_api.py`: `41 passed`. |
| Doc/test follow-ups | Web comment and the parent-code input placeholder now show the 16-hex shape; the existing fake code `BGPT-DEADBEEF` in tests still parses (schema min length 8). |

## R-04 · Admin triage queue reported a failure as "loading" (`F-05`, P2)

| | |
|---|---|
| Files | `apps/web/src/pages/AdminDashboard.tsx`, `apps/web/src/test/admincenter.test.tsx` |
| Root cause | `.catch(() => setQueue(null))` collapsed "failed" into "not loaded yet", and the render treated `null` as loading. |
| Change | New `triageErr` state; a failure renders `role="alert"` with the mapped message plus a retry button that re-runs the fetch; success clears the error. |
| Tests (test-first) | `admincenter.test.tsx::shows a retryable error when the feedback queue fails instead of loading forever`. Non-vacuity verified by patching the render back to the pre-fix shape, running the file (1 failed) and restoring (verified byte-identical). |

## R-05 · Chapter fetch error reported as an empty subject (`F-06`, P2)

| | |
|---|---|
| Files | `apps/web/src/pages/student/LearnPage.tsx`, `apps/web/src/test/workspace.test.tsx` |
| Root cause | `query.isError \|\| !content` shared one branch, which rendered `t("noChapters")`. |
| Change | Split the branches: an error renders the mapped message with a retry button (re-runs the query); "no chapters" is reserved for the genuinely empty case. |
| Tests (test-first) | `workspace.test.tsx::read tab reports a failed fetch as an error, not as an empty subject`. Non-vacuity verified with the same patch/restore procedure (failed pre-fix). |

## R-06 · Unrendered `{chapters}` placeholder in the student report (`F-25`, P2)

| | |
|---|---|
| Files | `apps/web/src/lib/text.ts`, `apps/web/src/pages/student/MePage.tsx`, `apps/web/src/pages/ParentDashboard.tsx`, `apps/web/src/test/meReport.test.tsx` |
| How it was found | The live browser pass reproduced it: the report card printed "দুর্বল অধ্যায়গুলোতে বেশি অনুশীলন করুন: **{chapters}**।" (`screenshots/student-me__desktop__placeholder-chapters.png`). |
| Root cause | The API deliberately returns `suggestion_code` + `suggestion_params` and the client composes the sentence (`_window_report` in `routers/parent.py`). `ParentDashboard` did that correctly; `MePage` called `t(code)` with no vars, so the placeholder survived to the screen. |
| Change | Extracted the existing parent-dashboard logic into `lib/text.ts::suggestionSentence()` (arrays joined with ", ", unknown codes fall back to the raw code) and used it from both pages, removing the duplicate. `MePage` now renders the composed sentence. |
| Tests (test-first) | New `src/test/meReport.test.tsx` (4 tests): full render with `sugg_practice_weak` asserting the sentence and that `{chapters}` is absent; `sugg_keep_momentum` numeric substitution; unknown-code fallback; missing-params case. Non-vacuity verified (1 failed against the pre-fix render, restored byte-identical). |
| Live evidence | `screenshots/student-me__desktop__report-after-fix.png` + the verification note in `UI_UX_ANTI_SLOP_REVIEW.md`. |

## R-07 · Two misleading comments (`F-07`, P3)

| | |
|---|---|
| Files | `apps/web/src/pages/student/LearnPage.tsx` (bookmark-save catch) |
| Change | Replaced a copy-pasted "best-effort: a parse failure must not block startup" (wrong rationale, appeared verbatim at three unrelated call sites) with the real reason. |

## R-08 · Documentation drift, six clusters (`F-08`, P3)

Files: `docs/API.md`, `docs/runbook.md`, `CONTRIBUTING.md`,
`docs/RAG_ARCHITECTURE.md`, `docs/architecture.md`, `docs/README.md`.

Each claim was verified against the named source before editing, and the full
diff was reviewed line by line afterwards. Highlights:

- `docs/API.md` no longer claims `/health` returns version/env, no longer marks
  `/metrics` as unauthenticated, and no longer claims every response carries
  `X-Request-ID`.
- `docs/runbook.md`'s three commands that failed verbatim
  (`python -m venv.venv`, `cp.env.production.example.env`) now run, and the web
  dev instruction uses `npm ci` to match CI.
- `CONTRIBUTING.md` no longer claims ESLint is uncommitted, marks prettier as a
  local-only check, and lists `mypy src` in the checks table.
- `docs/RAG_ARCHITECTURE.md` and `docs/architecture.md` now describe the
  retrieval that actually ships (hybrid: BM25 + deterministic model-free vector
  lane, RRF k=60, lexical rerank) instead of "lexical-only / dense pending", and
  the Docker/Alembic/Redis-limiter/golden-eval/Capacitor statements match the
  repository. `docs/architecture.md`'s body-size figure was corrected from
  "64 KiB" to the real default of 4,000,000 bytes — a mismatch found while
  reviewing this diff, not reported by the earlier sweep.
- `docs/README.md` no longer describes the route inventory as generated (no
  generator exists).

## Not changed, on purpose

| Item | Why |
|---|---|
| 7 prettier-failing files (`F-16`) | Mechanical churn across the owner's in-progress files (`i18n.ts`); not a CI gate. Should be its own commit. |
| Release workflow hardening (`F-10`) | Gates real releases and cannot be executed here; an untested change to the release path is worse than the documented risk. |
| `SEC-009` cross-tenant chapter content (`F-09`) | Requires a product decision (add tenancy vs. document shared content) plus a migration. |
| Accessibility gaps (`F-13`) | Screen-reader behaviour cannot be verified in this environment; changing `aria-live` scope blind risks making announcements worse. |
| Untracked Android assets (`F-12`) | Committing binaries is an owner action; this audit does not commit. |
| `tests/test_cors.py` additions | Kept in the existing CORS test module rather than a new file, so the preflight/error coverage sits with the rest of the CORS contract. |

## Diff hygiene

- Reviewed the full diff for generated files, lockfile churn, line-ending
  churn and unrelated edits: none introduced.
- The working tree already contained the owner's changes before this audit;
  the files touched here are listed above. `git status` scope is reported in
  `AUDIT_SUMMARY.md`.
- No secret, credential, private dataset or production artifact was added.
- Temporary artifacts created by this audit (dev servers, an isolated SQLite
  DB, a throwaway Vite config) are listed in `AUDIT_SUMMARY.md` §Cleanup.
