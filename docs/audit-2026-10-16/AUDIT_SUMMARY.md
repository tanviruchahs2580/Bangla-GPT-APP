# AUDIT SUMMARY — Bangla GPT APP (2026-10-16)

## Verdict

**NOT RELEASE-READY (NO-GO)**, audit scope **PARTIALLY VERIFIED**.

Three P1 findings remain unresolved, so the release gate is not met; and the
parts of the system that need provider or production access could not be
verified from here. Everything reachable from this checkout *was* verified and
is green: **API 828 passed / 6 skipped**, **web 162 passed / 48 files**, lint,
format, type checks, web build, migrations, guardrail scripts, and a live
browser pass over 12 screens against a running stack. Full reasoning in
`RELEASE_READINESS.md`.

## Scope actually completed

| Item | Value |
|---|---|
| Repository | `C:\Users\DST\projects\Bangla GPT APP` (= git root), branch `main` |
| Baseline commit | `bbac954` ("Full engineering audit + remediation: 47 findings fixed, 0 open (#1)") |
| Working tree at start | DIRTY — the owner's in-progress work (19 modified files, 1 staged rename, 24 untracked paths); **preserved, never reverted or reformatted** |
| Working tree at end | 62 entries: the owner's original 44 plus 18 added by this audit (listed in §Files changed) |
| Remote actions | **None.** No commit, push, PR, deploy, or provider setting change |
| Modules reviewed | 12 API routers (136 operations incl. 1 FastAPI built-in → 135 application operations), 25 services, retrieval/NCTB/eval subsystems, 22 frontend routes, 48 web test files, 4 CI workflows, 27 migrations, all live docs, Docker/compose, Capacitor Android |
| Runtime evidence | Local only: isolated API on `127.0.0.1:8010` (mock provider, throwaway SQLite) + SPA on `localhost:5273`; 38 screenshots at 1366×768 and 390×844 |
| Provider access | None — GitHub settings, remote CI runs, production/staging, Vercel project, Android signing are `NOT VERIFIED` |

## Confirmed stack and architecture

Monorepo, versions verified from the code rather than assumed:

- **API** — Python 3.12.10, FastAPI 0.143, SQLAlchemy 2.0, Alembic (27 revisions, single head `f2b3c4d5e6f7`), pydantic v2, SQLite by default with Postgres supported, Argon2id + TOTP, Redis-or-memory rate limiting, ARQ/background jobs, Prometheus metrics, Sentinel/Sentry hooks.
- **Web** — React 18.3 + Vite 5 + TypeScript 5.6, react-router 7, TanStack Query 5, react-markdown + KaTeX, i18next-style custom i18n (580 keys × bn/en), Vitest 4 + Testing Library + axe, Capacitor 7 Android shell.
- **AI** — provider abstraction (mock/gemini/openai) with a fast lane, fallback routing and a circuit breaker; hybrid retrieval (BM25 + dependency-free deterministic hashing embedder, RRF k=60, lexical rerank) over a chunked NCTB corpus with page provenance; prompt-injection hardening at prompt-build **and** ingestion time; per-user cost ledger with a hard 429 cap; a 634-case golden evaluation with a ±2 pp regression gate.
- **Deployment** — Dockerfile (non-root, digest-pinned base) + compose profiles (api/redis/web/tls/monitoring), GHCR release images with provenance attestations, Vercel for the SPA, SSH deploy job with rollback.

## Baseline commands and results

| Command (in `apps/api`) | Result |
|---|---|
| `ruff check .` / `ruff format --check .` / `mypy src` | exit 0 / 0 / 0 |
| `pytest -q` | **824 passed, 6 skipped** (664s) |
| `alembic heads` | `f2b3c4d5e6f7` single head |
| `alembic upgrade head` + `alembic check` on a **fresh** DB | no new operations (the local dev DB's "not up to date" was an environment artifact, not drift) |
| `npm run lint` / `vitest run` / `npm run build` (apps/web) | exit 0 / **156 passed** (47 files) / exit 0 |
| `npx prettier --check src` | **exit 1 — 7 files** (not a CI gate) |
| `check_readme_contract.py` | **exit 1 — dead link** (fixed here) |
| `check_changelog.py` / `check_i18n.py` | exit 0 / exit 0 (580/580 keys, parity 0) |

Logs: `logs/baseline_*.log`. Classification of the two non-zero results — one
pre-existing defect (fixed), one non-gate style drift and one environment
artifact (stale local DB) — is in `TEST_AND_CI_REPORT.md` §1.

## Findings

| Severity | Count | Fixed here | Open |
|---|---|---|---|
| P0 (critical) | 0 | 0 | 0 |
| P1 (high) | 5 | 2 | 3 |
| P2 (medium) | 12 | 5 | 7 |
| P3 (low) | 16 | 2 | 14 |
| **Total** | **33** | **9** | **24** |

Details, evidence and reproduction for every one: `AUDIT_FINDINGS.md`.
Per-requirement statuses: `AUDIT_TRACEABILITY_MATRIX.csv`.

**The nine fixed here:** a CI-blocking dead README link; cross-origin-unreadable
429/413 rejections (CORS was innermost); preflight requests consuming rate-limit
budget; 32-bit parent invite codes; an admin panel stuck on "loading" when its
queue fetch failed; a chapter fetch error presented as "no chapters"; a raw
`{chapters}` placeholder on the student's report; one misleading comment; and six
clusters of documentation drift.

**The three P1 blockers:** release workflow integrity (`F-10`), cross-school
read of generated chapter content (`F-09`), and a mobile APK that cannot be
built from a clean clone (`F-12`).

## Files changed by this audit

Owner-visible separation matters, because some files now carry both the owner's
in-progress work and this audit's changes:

**New (this audit only):**
`docs/audit-2026-10-16/**` (10 reports, 3 probes, 14 sanitized logs, 38 screenshots),
`apps/web/src/test/meReport.test.tsx`.

**Modified by this audit:**
`README.md`, `CONTRIBUTING.md`, `docs/API.md`, `docs/README.md`,
`docs/RAG_ARCHITECTURE.md`, `docs/architecture.md`, `docs/runbook.md`,
`apps/api/src/bangla_gpt_api/initialize/middleware_stack.py`,
`apps/api/src/bangla_gpt_api/routers/parent.py`,
`apps/api/tests/test_cors.py`, `apps/api/tests/test_product_v3.py`,
`apps/web/src/lib/text.ts`, `apps/web/src/pages/AdminDashboard.tsx`,
`apps/web/src/pages/ParentDashboard.tsx`, `apps/web/src/pages/student/MePage.tsx`,
`apps/web/src/pages/student/LearnPage.tsx`, `apps/web/src/api.ts`,
`apps/web/src/test/admincenter.test.tsx`, `apps/web/src/test/workspace.test.tsx`.

Note: `apps/web/src/api.ts`, `LearnPage.tsx` and `docs/README.md` already
contained owner edits; this audit's lines are additive and identified in
`REMEDIATION_LOG.md`.

## Second-pass review (independent critic, after remediation)

Adopting the role of a reviewer who did not write these changes:

1. **Root causes or symptoms?** Root causes. Each fix targets the cause named in
   the finding: registration order (not manually added CORS headers), the
   generator's entropy (not a longer rate limit), the conflation of failure with
   empty/loading (not a spinner tweak), and the missing params at the call site
   (not a hard-coded sentence).
2. **Any behaviour regressed?** *One deliberate, disclosed consequence:* with
   CORS now outermost, preflight `OPTIONS` requests no longer pass through
   Prometheus, so they are no longer counted in metrics, and they no longer
   carry `X-Request-ID`/security headers. HTTP preflights are browser
   infrastructure rather than user traffic, and the alternative (CORS inside the
   short-circuiting guards) is the defect being fixed. Recorded in
   `REMEDIATION_LOG.md` and `docs/API.md`. No other route, contract, role or
   screen changed; feature outcomes are recorded per surface.
3. **Would the new tests fail if the bug returned?** Yes — non-vacuity was
   *observed*, not assumed, for all four behaviour fixes (pre-fix runs failed;
   files restored byte-identical afterwards).
4. **Any gate weakened, typing loosened, error suppressed?** No. The suite grew
   (824→828, 156→162), no test was skipped or loosened, no `any`/`ts-ignore`
   added, and the one suppression that exists in app source (`ClassesPage.tsx:202`)
   was already there and is now unnecessary.
5. **Were secrets or student data exposed?** No secret values appear in any
   report or log. Test accounts were created on a throwaway database that has
   been deleted. One process note for full transparency: a session token for
   that ephemeral audit account was printed in a tool call during setup; it was
   signed with a local audit-only secret against the deleted database and has no
   access to anything.
6. **Can a new developer run this?** Yes, and better than before: three runbook
   commands that failed verbatim now work, the contributing guide's claim about
   a non-existent CI check is corrected, and the architecture/RAG docs describe
   what ships rather than what was once pending.
7. **Does every visual element serve a purpose?** In the 12 screens reviewed,
   yes — the remaining concerns are unverifiable statistics (`F-17`, `F-33`),
   the English-only status page (`F-31`), and the empty class selector (`F-26`),
   not decoration. No gradients/glow/blob filler was found.
8. **Anything unnecessary introduced?** The shared `suggestionSentence` helper
   *removes* a duplicate rather than adding one; the probes are audit artifacts,
   disposable by design. A purist could argue the helper belongs in its own
   module rather than `lib/text.ts` (which now imports i18n) — noted, not changed.
9. **Are all report claims backed by evidence?** Yes: every command result is in
   `logs/`, every UI claim has a screenshot or a reproduction path, and claims
   that could not be verified are labelled `NOT VERIFIED` rather than softened.
   One figure was corrected during this review (the body-size default, 64 KiB →
   4,000,000 bytes) and one doc sentence was softened from "multi-worker
   deployments use Redis" to "a shared Redis backend is available", because
   production configuration was never observed.
10. **Limitations stated plainly?** Yes — §Not verified below.

## Not verified (never counted as a pass)

GitHub branch protection, rulesets and required checks; secret scanning and push
protection; environment protection and required reviewers; remote CI run results;
whether the deployed image matches the attested digest; production/staging
health, latency, logs and TLS as served; real provider (Gemini/OpenAI) behaviour
and retention settings; Android release signing and device builds; screen-reader
behaviour; load/soak measurements; tablet and multi-device viewports; the
teacher generation flow end to end in the browser.

## Cleanup performed

- Audit dev servers stopped (ports 8010 and 5273, plus the second SPA server on
  5173); the pre-existing dev server on port 8000 was **not touched**.
- Temporary artifacts removed: `apps/web/vite.audit.config.ts`,
  `apps/api/.audit-dev.db`, the drift-check SQLite file, the temporary audit DB
  directory.
- No temporary file, generated artifact or secret was left in the tracked tree.
- This audit folder itself is new and untracked; the 38 screenshots are ~MB of
  binary evidence — committing them is the owner's choice.

## Report artifacts

| File | Contents |
|---|---|
| `AUDIT_SUMMARY.md` | This document |
| `AUDIT_FINDINGS.md` | All 33 findings with evidence, root cause, fix, tests, status |
| `REMEDIATION_LOG.md` | Ordered change log, test-first evidence, deliberate non-changes |
| `SECURITY_REVIEW.md` | Threat model, authz/authz review, privacy, residual risk |
| `TEST_AND_CI_REPORT.md` | Exact commands, counts, test-quality review, workflow review |
| `FEATURE_REGRESSION_MATRIX.md` + `.csv` | 136-row API surface + 22 frontend routes with outcomes |
| `UI_UX_ANTI_SLOP_REVIEW.md` | Page-by-page live review, anti-slop gate, a11y outcomes |
| `RELEASE_READINESS.md` | GO/NO-GO decision, blockers, prerequisites, rollback |
| `AUDIT_EXECUTION_LEDGER.md` | Phase log, commands, decisions, stopping point |
| `AUDIT_TRACEABILITY_MATRIX.csv` | Checklist A–R → status → evidence → findings → tests |
| `probes/`, `logs/`, `screenshots/` | Reproducible probes, sanitized logs, visual evidence |

## Next action requiring owner authorization

Nothing further can be verified without it: the owner must (1) push the combined
work so CI can run, (2) add the Android wrapper/launcher assets (`F-12`),
(3) decide `ChapterContent` tenancy (`F-09`), and (4) confirm environment
protection and digest-bound deploys (`F-10`). Any commit, push, deploy or
provider change is explicitly out of scope for this audit.
