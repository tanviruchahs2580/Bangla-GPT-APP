# AUDIT FINDINGS — Bangla GPT APP (2026-10-16)

Baseline commit `bbac954` on `main` + the owner's uncommitted working tree.
Evidence classes: **source** (file:line), **execution** (command + result),
**provider**, **runtime**. Confidence: CONFIRMED / PROBABLE / UNVERIFIED.

Status vocabulary: `FIXED` (post-fix evidence present), `OPEN`, `MITIGATED`,
`BLOCKED`, `ACCEPTED WITH RATIONALE`.

## Summary

Counting convention: one row per finding ID (`F-01`…`F-33`); rows that group
duplicate manifestations of one root cause (`F-08`, `F-14`) count once and list
their sub-items inside. `NOT VERIFIED` items are not findings and are excluded.

| Severity | Count | Fixed here | Open |
|---|---|---|---|
| P0 (critical) | 0 | 0 | 0 |
| P1 (high) | 5 | 2 | 3 |
| P2 (medium) | 12 | 5 | 7 |
| P3 (low) | 16 | 2 | 14 |
| **Total** | **33** | **9** | **24** |

Open items by area (24 total): data tenancy 1 (`F-09`) · release & CI/CD 6
(`F-10`, `F-20`, `F-21`, `F-22`, `F-23`, `F-24`) · security hardening 2
(`F-11`, `F-19`) · UI/UX & accessibility 10 (`F-13`, `F-14`, `F-26`…`F-33`) ·
performance & code hygiene 2 (`F-15`, `F-16`) · compliance & copy 2 (`F-17`,
`F-18`) · owner-blocked 1 (`F-12`).

Plus 6 items explicitly `NOT VERIFIED` (no access) — listed in
`AUDIT_SUMMARY.md`, not counted as findings.

---

## FIXED in this round

### F-01 · CI-BLOCK-01 · P1 · CI guardrail fails on a dead README link — FIXED
- **Category:** repository hygiene / release gate
- **Evidence (execution):** `.venv/Scripts/python.exe apps/api/scripts/check_readme_contract.py` → `::error::README links to a path that does not exist: docs/qa-audit-2026-10-06.md`, `EXIT=1`. The rename `docs/qa-audit-2026-10-06.md → docs/archive/…` is staged in the owner's tree, but the root `README.md:60` link was not updated.
- **Impact:** the `Repository guardrails` job in `ci.yml` fails on the current tree, so the release gate is red for a documentation link.
- **Root cause:** incomplete rename; `docs/README.md` was updated, root `README.md` was not.
- **Fix:** `README.md:60` now points at the current record `docs/qa-audit-2026-10-14.md` and links the archived one. **Post-fix evidence:** guardrail prints "README endpoint table agrees with the metrics gate and CI install command." `EXIT=0`.
- **Regression guard:** this script itself is the guard; it is wired into CI (`ci.yml` guardrails job).

### F-02 · API-CORS-01 · P1 · Rejections were unreadable by the cross-origin SPA — FIXED
- **Category:** API correctness / frontend-backend contract
- **Evidence (source):** `initialize/middleware_stack.py` registered `CORSMiddleware` first; Starlette prepends on `add_middleware`, so CORS resolved **innermost** (runtime stack printed by `probes/probe_middleware_order.py`: `… PrometheusMetrics → SecurityHeaders → RequestId → BodySizeLimit → RateLimit → CORSMiddleware → router`).
- **Evidence (execution, before):** probe `logs/probe_middleware_order.log` — 200/404 responses carry `access-control-allow-origin`; the 429 from `RateLimitMiddleware` and the 413 from `BodySizeLimitMiddleware` carry **none**, because both short-circuit before reaching CORS.
- **Impact:** the deployed topology is cross-origin (Vercel SPA → API, `ALLOWED_ORIGINS` configured, `VITE_API_BASE` documented for native builds). A rate-limited or oversized request therefore surfaces in the browser as an opaque network/CORS failure instead of the structured `{"detail":{"code":"rate_limited"}}` payload that `errors.ts::friendlyError` maps to user-facing copy. Rate limiting is exactly the state where the user needs to be told to slow down.
- **Root cause:** middleware registration order inverted relative to the documented intent; the docstring at `middleware_stack.py:69-78` asserted the registration order *was* the execution order (misleading comment).
- **Fix:** CORS is registered last (outermost); the docstring now states the real Starlette semantics and why CORS must stay outermost.
- **Tests (new, non-vacuous):** `tests/test_cors.py::test_rate_limited_response_is_readable_cross_origin`, `::test_oversized_body_response_is_readable_cross_origin`. Both fail on the pre-fix order (verified: `3 failed, 4 passed` before the fix; `30 passed` after, together with the 4 pre-existing CORS tests and the rate-limit/metrics suites).
- **Post-fix evidence:** `logs/probe_middleware_order.after.log` — 429 and 413 both carry `access-control-allow-origin` plus the CSP/nosniff headers; runtime order starts `CORSMiddleware`.

### F-03 · API-RATE-01 · P2 · CORS preflights consumed the rate-limit budget — FIXED
- **Category:** API correctness / abuse control
- **Evidence (execution, before):** `probes/probe_preflight_budget.py` with `RATE_LIMIT_LOGIN_PER_MINUTE=2` → without a preflight `[401, 401, 429]`; with the browser's OPTIONS preflight first `[401, 429, 429]` (`logs/probe_preflight_budget.log`).
- **Impact:** every browser-rendered login attempt halves the configured budget (5 real attempts for a 10/min limit), and the same applies to `/tutor/ask`, `/events`, and each teacher AI generator — a student or teacher hits the wall at half the intended rate.
- **Root cause:** same as F-02 — the preflight was denied a chance to be answered by CORS, so it travelled through `RateLimitMiddleware` and was counted.
- **Fix:** same change; CORS now answers preflights before the limiter runs.
- **Tests:** `tests/test_cors.py::test_preflight_does_not_consume_rate_limit_budget` (fails pre-fix with `assert [401, 429] == [401, 401]`).
- **Post-fix evidence:** probe step [3] — with the preflight sent first and a 1/min limit, the first POST is `401` (allowed) and the second is `429`. Trade-off recorded: preflight responses no longer carry `X-Request-ID`/CSP (they are answered by CORS before those middlewares), documented in `docs/API.md`.

### F-04 · SEC-007 · P2 · Parent invite code carried only 32 bits — FIXED
- **Category:** authorization / minor-data protection
- **Evidence (source):** `routers/parent.py:169` `code = "BGPT-" + secrets.token_hex(4).upper()` → 4 bytes = 32 bits = 4.29e9 candidates; TTL 1440 min; ≤3 live codes per student; redemption is atomic and single-use.
- **Impact:** the code is the only secret between a stranger and a **parent link onto a child's record** (which grants that child's learning report and digest). 32 bits is inside the reach of a distributed guesser over a 24-hour TTL; the per-IP limit (10/min) only constrains a single address.
- **Root cause:** code length chosen for typability without an entropy budget.
- **Fix:** `secrets.token_hex(8).upper()` → 64 bits. Backward compatible: redemption looks the code up by hash, and the request schema already accepts 8–128 chars, so previously issued 8-hex codes still redeem. Web hint/comment updated (`api.ts:420`, `ParentDashboard.tsx:120`).
- **Tests:** `test_product_v3.py::test_parent_invite_code_carries_enough_entropy` (fails pre-fix: 32 bits < 64). Whole file green post-fix (41 passed with the neighbouring suites).

### F-05 · UI-ERR-01 · P2 · Feedback triage failed as an endless "loading" state — FIXED
- **Category:** UI correctness / misleading state
- **Evidence (source):** `pages/AdminDashboard.tsx:63-67` swallowed the error with `.catch(() => setQueue(null))`, and the render treated `queue === null` as loading (`:341-344`).
- **Impact:** an admin whose queue fetch fails sees `লোড হচ্ছে…` forever — indistinguishable from a slow network, with no retry and no clue the triage queue is down.
- **Fix:** dedicated `triageErr` state; failures render `role="alert"` with the mapped message and a retry button; success clears it.
- **Test (new, non-vacuous):** `src/test/admincenter.test.tsx::shows a retryable error when the feedback queue fails instead of loading forever`. Empirically verified to fail against the pre-fix render (patch-and-restore run: 1 failed) and pass after (14 passed with neighbouring files).

### F-06 · UI-ERR-02 · P2 · A chapter fetch error was reported as an empty subject — FIXED
- **Category:** UI correctness / misleading empty state
- **Evidence (source):** `pages/student/LearnPage.tsx` rendered `t("noChapters")` ("No chapters found for this subject") for `query.isError || !content`.
- **Impact:** a network/server failure told the student the curriculum has no content for that subject — a false statement about the product's own corpus — with no way to retry.
- **Fix:** the error branch now renders the mapped failure message with a retry button (re-runs the query); the "no chapters" copy is reserved for the genuinely-empty case.
- **Test (new, non-vacuous):** `src/test/workspace.test.tsx::read tab reports a failed fetch as an error, not as an empty subject` (verified failing pre-fix).

### F-07 · UI-COPY-01 · P3 · Copied rationale comment described the wrong failure — FIXED
- **Evidence (source):** `LearnPage.tsx` bookmark-save `catch` carried "best-effort: a parse failure must not block startup" (identical text to two unrelated call sites).
- **Fix:** comment now states the real reason (a failed book-mark write must not drop the reader out of the chapter).

### F-08 · DOC-01…06 · P3 · Documentation contradicted the code — FIXED
Six drift clusters, each verified against source before editing; all edits are
surgical and the diff was reviewed line by line.

| ID | Doc | Was | Now (verified against) |
|---|---|---|---|
| DOC-01 | `docs/API.md:12` | `/health` returns "app/version/env" | Liveness only; version/env live on authenticated `/admin/system/info` (`routers/system.py`) |
| DOC-02 | `docs/API.md:15` | `/metrics` auth "—" | open in dev; `Bearer $METRICS_TOKEN` in production (`routers/system.py`, `main.py::_validate_metrics`) |
| DOC-03 | `docs/API.md:17` | "Every response carries `X-Request-ID`" | non-preflight responses only (consequence of F-02, verified by probe) |
| DOC-04 | `docs/runbook.md:10,29,37` | `python -m venv.venv`; `npm install`; `cp.env…` (three commands that fail verbatim) | `python -m venv .venv`; `npm ci` (matches CI); `cp .env.production.example .env` |
| DOC-05 | `CONTRIBUTING.md:36,42,44` | "ESLint config is not committed yet"; format marked as a CI check; no type-check row | ESLint config is committed and CI runs `npm run lint`; prettier marked local-only; `mypy src` row added (`ci.yml` web/api jobs) |
| DOC-06 | `docs/RAG_ARCHITECTURE.md:49-59`, `docs/architecture.md:19,60-64,84,133-141,142-143,238-239`, `docs/README.md:17` | "Dense/Hybrid merge/Reranker pending", "lexical-only", "Docker deferred", "Alembic migrations pending", rate limiting "in-memory only … pending", retrieval "BM25", golden benchmark + Flutter mobile listed as pending, body-size "default 64 KiB", route inventory "generated" | hybrid retrieval with a deterministic model-free embedder (RRF k=60 + lexical rerank) is what ships; Docker/Alembic/Redis-limiter/golden-eval all exist; mobile is Capacitor Android; body-size default 4,000,000 bytes; route inventory hand-maintained (`config.py`, `retrieval/*`, `alembic/versions`, `ci.yml`, `apps/api/eval/*`, `apps/web/android`) |

### F-25 · UI-REPORT-01 · P2 · A raw `{chapters}` placeholder was shown to students — FIXED
- **Category:** UI correctness / i18n
- **How it was found:** the live browser pass reproduced it on `/student/me` — the report card rendered "দুর্বল অধ্যায়গুলোতে বেশি অনুশীলন করুন: **{chapters}**।" (`screenshots/student-me__desktop__placeholder-chapters.png`).
- **Evidence (source):** the API returns `suggestion_code` + `suggestion_params` and the client composes the sentence (`routers/parent.py:588-610`, comment "Code + params only -- the client renders the sentence"). `ParentDashboard.tsx:11-24` did that; `MePage.tsx:512-513` called `t(code)` with **no** vars, so the placeholder survived.
- **Impact:** any student (and only students — the parent view was correct) whose report triggered `sugg_practice_weak` saw a developer placeholder instead of their weak chapters. `sugg_keep_momentum` (`{avg_score_pct}`) was affected the same way.
- **Fix:** extracted the existing parent logic into `lib/text.ts::suggestionSentence()` and used it from both pages (removes the duplicate); `MePage` now renders the composed sentence.
- **Tests (new, non-vacuous):** `src/test/meReport.test.tsx` (4 tests) — verified failing against the pre-fix render, passing after.
- **Live post-fix evidence:** `screenshots/student-me__desktop__report-after-fix.png`; the rendered sentence was confirmed as "পরামর্শ: দুর্বল অধ্যায়গুলোতে বেশি অনুশীলন করুন: পানিচক্র।" with a page-wide scan finding zero `{...}` placeholders and the chapter matching the report chip.

---

## OPEN — no safe local fix in this round

### F-09 · SEC-009 · P1 · Generated chapter content is readable across schools — OPEN
- **Evidence (source):** `db/models.py:390-418` — `ChapterContent` is keyed by `subject/class_level/chapter/version` with no school or owner column; `routers/teacher_content.py:258` (`GET /teacher/content`) and `:223` (`GET /teacher/content/history`) filter only by subject/class/chapter; `PUT /teacher/content` (`:272`) can append versions to another school's material.
- **Impact:** any authenticated teacher can read and extend content generated under another school's tenancy. No student-facing endpoint reads this table, so the exposure is peer-to-peer between schools rather than to students.
- **Root cause:** the table was built as a shared subject/chapter content cache before school tenancy existed; sharing may even be intended (the versioning scheme is content-keyed, not author-keyed).
- **Why not fixed:** either resolution is a product decision with a migration — (a) add `school_id` + scope reads/writes, or (b) declare the cache intentionally global and document it. Patching (a) blindly would silently remove cross-school content reuse that the current versioning scheme implies.
- **Recommendation:** decide the tenancy model, then implement with a data migration and a cross-school negative test in the style of `tests/test_school_tenancy_isolation.py`.
- **Related (lower risk, same theme):** `routers/school.py:886-890` (school coverage reads chapters by class level across schools, aggregate only).

### F-10 · CI-REL-01 · P1 · Release deploys code that CI never verified — OPEN
- **Evidence (source):** `release.yml` triggers on tags `v*.*.*` only (`:8-10`); `ci.yml` and `eval-gate.yml` do not run on tags (`:4-7`, `:10-13`); the deploy job `needs: build-push` (`:174`) has no dependency on any test job; the deploy host pulls by **tag** (`docker compose pull`) after `git checkout "$RELEASE_TAG"` (`:226-239`) although the workflow records image **digests** (`:111-128`).
- **Impact:** any commit can be tagged and shipped without lint/tests/eval, and a mutable GHCR tag could resolve to a different image than the attested one.
- **Why not fixed:** a release-path change cannot be executed or observed from this environment, and a wrong gate would block real releases — strictly worse than the current state. `environment: production` (`:179`) is referenced, but nothing in-repo proves required reviewers are configured (provider-side).
- **Recommendation:** (1) have `release.yml` verify that the tagged SHA has successful `ci` + `eval-gate` runs (or add `workflow_run`/reusable-workflow wiring); (2) deploy the recorded digest (`image@sha256:…`) instead of the tag; (3) confirm the `production` environment requires reviewers; (4) cover all ecosystems in `dependabot.yml` (compose images are not covered).

### F-11 · SEC-008 · P2 · CSV roster import performs up to 200 Argon2id hashes per request — OPEN
- **Evidence (source):** `routers/teacher.py:64` (`IMPORT_MAX_ROWS = 200`), one `hash_password()` per row (`:289-292`), Argon2id t=2/m=19 MiB/p=1 (`auth/security.py:19`).
- **Mitigation already present:** per-user rate limit `/teacher/classrooms` 30/min. Worst case ≈ 200 × 30 = 6000 hashes/min for an authenticated teacher, which is a real CPU cost on a small instance but bounded and attributable.
- **Why not fixed:** lowering the cap or moving hashing to a background job changes an existing product behaviour (import UX) and needs an owner decision; not a security bug.

### F-12 · GIT-001 · P1 (mobile release) · The Android APK cannot be built from a clean clone — BLOCKED
- **Evidence (source/execution):** `apps/web/android/gradle/wrapper/gradle-wrapper.jar`, `res/mipmap-*`, `res/drawable*/`, `res/xml/data_extraction_rules.xml` and `res/drawable/splash.png` are untracked (`git status --porcelain`), while `androidManifest.test.ts` reads `AndroidManifest.xml` from the tree.
- **Impact:** a fresh clone cannot assemble a release APK, so mobile releases are not reproducible from the repository.
- **Why blocked:** committing binaries is an owner action; this audit does not commit (and the owner's `.gitignore` was already adjusted for exactly this). **Owner action:** `git add` the wrapper + launcher/splash assets and verify `./gradlew assembleRelease` on a clean clone.

### F-13 · A11Y-001/002 · P2 · Accessibility gaps in the app shell and chat — OPEN
- **Evidence (source):** `components/AppShell.tsx` (whole file) has no `<h1>` and no skip-to-content link; `pages/student/AITutorPage.tsx:496-501` puts `aria-live="polite"` on the **entire thread container** so every streamed token re-announces growing content; `AdminDashboard.tsx:658-673` pagination buttons contain only `‹`/`›` with no accessible name; `LearnPage.tsx:863-872` (chapter question) and `ClassesPage.tsx:586-592` (CSV paste) are placeholder-only inputs; `NotificationBell.tsx:83-120` exposes `role="menu"`/`menuitem` without arrow-key or Escape handling; tab/radio groups (`ui.tsx:367-400`, `QuizPage.tsx:354-365,466-499`) lack arrow-key support.
- **Why not fixed:** each is small but touches shared components, and the correctness of screen-reader behaviour cannot be verified in this environment (no assistive tech). Changing `aria-live` scope without that verification risks making announcements worse.
- **Recommendation:** add a skip link + one `<h1>` per page shell; move the live region to a dedicated status node that announces "answer started/finished"; add `aria-label`s to the pagination controls; label the two inputs; implement or downgrade the ARIA menu/tab patterns. Verify with a screen reader before/after.
- **Positive findings (verified):** icon-only buttons elsewhere have `aria-label`s; `ui.tsx` Modal traps focus, restores it, locks scroll and closes on Escape; `ClassesPage.tsx:555-561` supplies visually-hidden health text so status is not colour-only.

### F-14 · UI-STATE-01…04 · P2/P3 · Other silent-failure and inert-control states — OPEN (PROBABLE)
Source-level review; **not** reproduced in a browser (see the visual-pass limits in
`UI_UX_ANTI_SLOP_REVIEW.md`). Confidence PROBABLE unless noted.

| ID | Sev | Evidence | Problem |
|---|---|---|---|
| UI-STATE-01 | P2 | `pages/student/MePage.tsx:377-383` vs `:122-138,354-362` | The AI-memory switch only mutates local state; persistence happens in a Save button in a different card, so the toggle looks saved and is silently discarded |
| UI-STATE-02 | P2 | `pages/teacher/CreatePage.tsx:319,406-417` | "Assign short test" stays enabled with no classroom selected and silently returns; a failed list fetch renders the "empty" copy |
| UI-STATE-03 | P3 | `pages/teacher/CreatePage.tsx:571-599` | Lesson-plan section edits live only in component state (print-only flow), so typed edits vanish on navigation |
| UI-STATE-04 | P3 | `components/SearchBox.tsx:44-47`, `AITutorPage.tsx:317-332` | A failed search renders as "no results" — a failure is indistinguishable from an empty result set |

### F-15 · PERF-001 · P3 · `/assignments/mine` filters in Python — OPEN
- **Evidence (source):** `routers/assessment.py:796-810` loads up to `le=500` (default 200) assignment rows and filters `attempts` membership in Python; attempt rows are fetched in one batched query (`:811-820`), so there is no N+1.
- **Impact:** bounded and small at current scale; correctness is unaffected.
- **Recommendation:** push the membership predicate into SQL when the dataset grows.

### F-16 · STYLE-001 · P3 · Seven files fail `prettier --check` — OPEN
- **Evidence (execution):** `npx prettier --check src` → `Code style issues found in 7 files` (`i18n.ts`, `lib/apiProxy.ts`, `lib/text.ts`, `pages/LoginPage.tsx`, `styles.css`, `test/apiProxy.test.ts`, `test/login.test.tsx`). Prettier is a local script only — CI does not run it.
- **Why not fixed:** `i18n.ts` is part of the owner's uncommitted work; reformatting it here would add unrelated churn to their diff. Mechanical formatting should be its own change.
- **Recommendation:** run `npm run format` in a dedicated commit, then decide whether to gate it in CI (adding the gate before the cleanup would red the pipeline).

### F-17 · COPY-001 · P3 · Unverifiable marketing statistic — OPEN
- **Evidence (source):** `i18n.ts:29-30` (bn) / `:652-653` (en) — "১০০% / বাংলা-প্রথম অভিজ্ঞতা" rendered on `pages/WelcomePage.tsx:111-112`. Nothing in the product measures a share of Bangla-first interactions.
- **Recommendation:** replace with a claim the repository can support (e.g. the curriculum span already covered by `landingStats.test.ts`) or delete the tile.

### F-18 · ENV-01 · P3 · `.env.production.example` omits ~20 settings — OPEN
- **Evidence (source):** settings with no entry (not even commented) in `.env.production.example`: `AI_MONTHLY_BUDGET_USD_PER_USER`, `APP_NAME`, `CIRCUIT_BREAKER_FAILURE_THRESHOLD`, `CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS`, `FORCE_ADMIN_PASSWORD_CHANGE`, `JWT_AUDIENCE`, `JWT_ISSUER`, `LLM_FALLBACK_PROVIDER`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `PARENT_DIGEST_CHECK_MINUTES`, `PARENT_DIGEST_ENABLED`, `RATE_LIMIT_RULES`, `SENTRY_DSN`, `SENTRY_ENV`, `TRUST_PROXY_HEADERS`, `VERSION`, `WEAKNESS_REFRESH_CHECK_MINUTES`, `WEAKNESS_REFRESH_ENABLED`. `.env.example` itself has full parity (enforced by `tests/test_env_example.py`).
- **Impact:** an operator following only the production example cannot discover fallback-provider, budget, or Sentry configuration.

### F-19 · SEC-ENTROPY-02 · P3 · School invite code is 50 bits — OPEN
- **Evidence (source):** `routers/school.py:339` — 10 chars from a 32-symbol alphabet ≈ 50 bits; school code 8 chars ≈ 40 bits (`:96`); teacher CSV initial credentials use `token_urlsafe(9)` ≈ 72 bits (`routers/teacher.py:289`). Only the parent invite (F-04) was materially short.

### F-20 · AI-EVAL-01 · P3 · The eval gate fails open when its baseline is missing — OPEN
- **Evidence (source):** `evaluation/cli.py:155-157` — if `eval/baseline_v2.json` is absent the CLI reports without gating and exits 0 (`metrics.py:227-253` is the real comparison, `GATE_PP = 2.0`).
- **Impact:** deleting/renaming the baseline silently disables the regression gate; the file is tracked, so this is a robustness gap rather than an active defect.

### F-21 · CI-INSTALL-01 · P3 · Eval-gate install is not hash-verified — OPEN
- **Evidence (source):** `eval-gate.yml:37,43` caches on `pyproject.toml` and installs `-e ".[dev]"` without `--require-hashes`, unlike every job in `ci.yml` (`:51,162,209`).

### F-22 · CI-COMPOSE-01 · P2 · Compose publishes the API on all interfaces when a variable is unset — OPEN
- **Evidence (source):** `docker-compose.yml:64-65` — `ports: - "${API_HOST_PORT:-}:8000"`; an empty host port still publishes on a random port bound to `0.0.0.0`, contradicting the comment above it (`:62-63`) which says the port is published "ONLY when `API_HOST_PORT` is set".
- **Recommendation:** move the mapping into an override file, or bind `127.0.0.1:` explicitly.

### F-23 · CI-DOCKER-01 · P2 · The web image build bakes local `.vercel` material into build layers — OPEN
- **Evidence (source):** `apps/web/Dockerfile:7` does `COPY . .` with no `.dockerignore` in `apps/web`; `.vercel/.env.development.local` (gitignored) contains a Vercel OIDC JWT. The final nginx stage copies only `dist`, so the shipped image is clean, but build-stage layers/cache can retain the file.
- **Recommendation:** add `apps/web/.dockerignore` (`.vercel`, `node_modules`, `.env*`, `android`) — small and self-contained.

### F-24 · CI-VER-01 · P2 · Production deploy is gated on the API job only — OPEN
- **Evidence (source):** `vercel-deploy.yml:11-14` triggers on `workflow_run` of "API CI" and correctly checks `conclusion == 'success'`, `event == 'push'`, `head_branch == 'main'`, `head_repository == github.repository` (`:33-38`); it does **not** consider `eval-gate.yml`, so a green CI with a failed AI regression gate still deploys to production.

## Findings from the live browser pass (reproduced on screen)

38 screenshots in `screenshots/` (37 from the main pass plus the after-fix re-capture); the pass ran against an isolated local stack
(API on `127.0.0.1:8010`, mock LLM provider, throwaway SQLite database, SPA on
`localhost:5273`). Every item below was observed in the rendered UI, not
inferred from source. Details and page-by-page results are in
`UI_UX_ANTI_SLOP_REVIEW.md`.

### F-26 · UI-EMPTY-01 · P2 · The grade selector offers classes with no content and shows a blank page — OPEN
- **Evidence (runtime):** `/student/learn` offers শ্রেণি 1–12 (`i18n.ts` class chips), but only class 6 has corpus content. Selecting শ্রেণি 1 renders **zero** subject cards and no message — the catalogue area is simply empty (`screenshots/student-learn__desktop__grade1-empty.png`).
- **Impact:** a student browsing outside class 6 concludes the app is broken; there is no "no content for this class yet" state and no guidance back to a class that has content.
- **Root cause:** the class list is a hard-coded range (`LearnPage.tsx:53-54` allows 1–12) while the content/corpus actually covers 6–10 (`landingStats.test.ts` guards exactly that claim); the empty branch has no UI.
- **Recommendation:** derive the offered classes from the content API (or mark unavailable classes) and render an explicit empty state with a way back.

### F-27 · UI-CITE-01 · P3 · The evidence row shows the same citation chip twice — OPEN
- **Evidence (runtime):** the tutor answer's source row renders `কোষ | কোষ | মানবদেহ ও পুষ্টি` — two identical `button.source-chip` entries (`screenshots/student-tutor__desktop__answer-streamed.png`, `...evidence-modal.png`).
- **Impact:** duplicated provenance reads as a rendering bug and weakens trust in the citation; the evidence modal inherits it.
- **Root cause (source):** citations are built per retrieved hit (`services/tutor.py:294-307`) without de-duplicating by `(book, chapter, section, page)`.

### F-28 · UI-KEY-01 · P3 · React list-key console errors on two teacher pages — OPEN
- **Evidence (runtime, console):** "Each child in a list should have a unique `key` prop" logged on `/teacher` (`TeacherHomePage.tsx:41`) and `/teacher/create` (`CreatePage.tsx:1136`). No other console errors appeared anywhere in the pass.
- **Impact:** no visible corruption in the observed states, but a real code defect — React can mis-reconcile these lists on update (duplicate/missing rows), and it is the only console noise the app emits.
- **Recommendation:** give the mapped items stable keys (an id, not an index or label).

### F-29 · UI-MOBILE-01 · P3 · The mobile tutor composer is too narrow, so its placeholder is clipped — OPEN
- **Evidence (runtime, 390×844):** the composer input is ~134px wide (attach 32 + mic 44 + send 59 are fixed), so "পাঠ্যবই থেকে যেকোনো প্রশ্ন লিখুন…" renders as "পাঠ্যবই থেকে যেকে" (`screenshots/student-tutor__mobile__composer.png`). No horizontal overflow exists at this width, and Bangla text wraps correctly elsewhere.
- **Recommendation:** let the input take the row and move secondary actions behind an overflow control on narrow viewports.

### F-30 · UI-A11Y-03 · P3 · Keyboard focus lands underneath the fixed mobile bottom bar — OPEN
- **Evidence (runtime):** at 390px, tabbing from the top of the tutor page moved focus to the style chips at y≈777–800, which sit under the fixed `.bottombar` (y 780–844); `elementFromPoint` at that position returns a bottom-nav item, so the focus ring is invisible. Reproduced on three consecutive stops.
- **Impact:** keyboard and switch-access users lose their place on small screens — a WCAG 2.4.11/2.4.7 concern.
- **Recommendation:** add scroll-padding/`scroll-margin-bottom` equal to the bar height, or hide the fixed bar while focus is inside the scroller.

### F-31 · UI-I18N-01 · P3 · The public status page is English-only with a US-formatted timestamp — OPEN
- **Evidence (runtime):** `/status` renders entirely in English ("Last checked: 10/16/2026, 3:14:23 AM") and shows a "লগইন" link while already authenticated (`screenshots/status__desktop__loaded.png`). The four `status*` keys are already on the i18n checker's `PENDING_BANGLA_REVIEW` allowlist, so this is a known, tracked gap rather than a surprise.
- **Recommendation:** translate the status copy and format the timestamp with the active locale (and `bn-BD` numerals when Bangla is selected).

### F-32 · UI-READER-01 · P3 · Three reader-control polish defects — OPEN
- **Evidence (runtime):** (a) the chapter badge shows the English slug `science` while the same page shows `বিজ্ঞান` as the heading (`screenshots/student-reader__desktop__loaded.png`) — `tSubject()` is not applied to the badge; (b) after the download button switches to "সংরক্ষিত" its `aria-label` stays "ডাউনলোড করুন" with no `aria-pressed`/announcement, so assistive tech reports a stale action; (c) the font-size slider scales only the body text (`div.reader-md`), leaving h1/h3 at a fixed size, so the control does less than it appears to.
- **Recommendation:** localize the badge via `tSubject`, make the saved state announced (`aria-pressed` + live region), and scale headings with the slider (or label it as body-text size).

### F-33 · UI-COPY-02 · P3 · A brand-new teacher account is shown a savings estimate — OPEN
- **Evidence (runtime):** `/teacher` renders "সাশ্রয়ী সময় (আনুমানিক)" = "প্রায় ০ মিনিট সাশ্রয় হয়েছে (আনুমানিক)" on a fresh account with no history (`screenshots/teacher-home__desktop__loaded.png`).
- **Impact:** an estimate computed from zero data is shown as a metric; it is the same class of unverifiable statistic as `COPY-001` (`F-17`).
- **Recommendation:** hide the tile until there is enough activity to estimate from, or replace it with a factual count.

### Verified as working during the pass (no defect — recorded so silence is not mistaken for absence)
Search typeahead, notifications (with a real empty state), language toggle
(persisted), dark mode (persisted across SPA navigation), bookmark
(`aria-pressed` + toast), offline download (writes to IndexedDB `bgpt-offline`),
quiz start → 5 questions → results → revision/assigned tabs, citation chip →
evidence modal with breadcrumb, teacher tiles → question-paper form, guardian
consent enforced on student registration, login → JWT, streaming tutor answer
over SSE, and no failed network request on any visited page.

### Not verifiable in this pass
Speech synthesis output (the host has no `bn-BD` voice, so a correct `speak()`
call is silent here), file attach and microphone capture (no OS devices in the
automation browser), teacher generation submit (requires an artifact name), and
the destructive account-deletion/export actions (deliberately not triggered).

---

## NOT VERIFIED (no access — counted separately, never as PASS)

GitHub branch protection / rulesets and required status checks; secret scanning
and push protection; environment protection rules and required reviewers;
whether the recorded image digest is what actually runs; production/staging
health, latency and logs; Android release signing and a device build;
screen-reader behaviour; load/soak measurements; the real provider (Gemini /
OpenAI) paths against live APIs; Vercel project settings. Remote CI runs were
never observed — every CI statement here is a source-review statement.

---

## Addendum — rebase onto the current `main` (2026-10-16, second session)

The first session's baseline was commit `bbac954`. While that work was in
progress the owner merged three PRs (#9, #10, #14), so `main` advanced to
`42ae3f9` and the branch conflicted. The audit's local clone held a stale
`origin/main` ref, which is why the divergence was not visible at the start;
the finding is recorded here rather than quietly fixed.

Rebasing onto `42ae3f9` changed the status of exactly two of this audit's
findings, and both corrections run in the *safe* direction:

| Finding | Status after rebase |
|---|---|
| `F-02` / `F-03` (CORS innermost: unreadable 429/413, preflights consuming budget) | **Already fixed upstream in PR #10** — `middleware_stack.py` on `main` registers CORS last and documents the reversed build order. This branch therefore **drops the code change and keeps the three regression tests**, which now run against upstream's implementation and pass; they are independent verification of that fix, not a duplicate. |
| `F-06` (chapter fetch error shown as "no chapters") | Re-checked on `main`: the misleading branch is still there, so the fix stays. |
| `F-25` (`{chapters}`), `F-34` (raw `memory_on_disable_note`), `F-35` (admin `school_admin` row), `F-36` (short-test classroom), `F-37` (mini-quiz count), `F-04` (invite entropy), `F-01`/`F-08` (docs), `F-12` (Android assets) | **Still needed** — verified absent on `42ae3f9` and re-applied. |
| `F-28` (React list-key warning), `F-13`/`F-30`, `F-38` and the other open items | Unchanged; still open. |

A new finding surfaced from the rebase itself:

### F-39 · REL-01 · P2 · The Bengali landing statistic contradicted the English one — FIXED
- **Evidence (source):** on `main`, `i18n.ts` had `statClassesValue: "১–১২"` for
  Bangla (line 25) while the English dictionary said `"6–10"` (line 654), and
  `index.html`'s meta description still advertised ১–১২ for a corpus that covers
  6–10 (`apps/api/src/bangla_gpt_api/data/sample_nctb`, guarded by
  `landingStats.test.ts`).
- **Impact:** the Bengali-facing claim was the false one — the audience most
  likely to read it. A student in class 1 would look for content that does not
  exist (see `F-26`).
- **Fix:** Bangla value aligned with the English one and with the corpus; the
  added `landingStats.test.ts` asserts the bn/en agreement and the corpus span.

Verification on the rebased base is in `LIVE_VERIFICATION_AND_DEPLOY_REPORT.md`
§4 and the `rebased_*` logs.

### What the rebase changed about the carried-over work (detail)

Porting the still-needed work onto `42ae3f9` was verified finding-by-finding
rather than by replaying diffs, because `main` had re-implemented parts of it.
The disposition of every carried item:

| Carried item | Disposition after rebase |
|---|---|
| CORS ordering + docstring | **Dropped** — PR #10 already implemented it; the three regression tests were kept and pass against upstream's version |
| `LearnPage` error branch, `MePage`/`lib/text` suggestion sentence, `AdminDashboard` triage error state, `AdminDashboard` role list, `CreatePage` classroom picker, `HomePage`/`QuizPage` count, `parent.py` invite entropy, `i18n` memory copy, docs corrections, Android assets, QA record, the carried test files | **Re-applied** — verified absent on `42ae3f9` before re-applying |
| Teacher rate-limit rules (`/teacher/*`, `/parents/link/invite`) in `config.py` | **Re-applied** — the carried `test_rate_limit_coverage.py` failed without them (9 failures), confirming they had never reached `main` |
| Per-user AI budget + usage ledger on document generators and question papers (`routers/common.py`, `routers/teacher_content.py`) | **Re-applied** — the carried `test_teacher_ai_budget.py` failed without them (6 failures). Without this, a teacher could spend provider tokens unbounded, and `/admin/ai/quality` under-reported every generator run |
| `api.ts`: logout clearing the parked admin token (SEC-006), `postStream` preserving the server's machine code and firing the 401 handler (BUG-004), `parseSse` frame framing + terminal-frame requirement (BUG-005) | **Re-applied onto main's newer `api.ts`** — `main` still flattened every stream failure to `llm_unavailable` (so a 429 read as "AI unavailable") and still resolved `null` for a truncated stream. The 8 carried tests fail against main's version and pass after the port |
| Android manifest hardening + `res/xml/data_extraction_rules.xml` | **Re-applied** — `main` still shipped the default Capacitor manifest (`allowBackup="true"`, no `RECORD_AUDIO`), so cloud backup of the WebView token store stayed enabled and Android dictation could not work |
| Quiz-submit transaction consolidation (BUG-003), verification-email delivery logging (BUG-001), bounded content-version retry loop (BUG-002) | **NOT carried over.** No carried test requires them, and they touch flows `main` has since changed; replaying them late would put currently-green behaviour at risk. Left as open findings with the original analysis, to be applied deliberately |

### F-40 · AI-BUDGET-01 · P2 · Teacher AI spend was neither budgeted nor metered on `main` — FIXED (re-applied)
- **Evidence (execution):** with the carried test file present and `main`'s code,
  `tests/test_teacher_ai_budget.py` failed 6/7 plus 9 rate-limit coverage
  failures — the document generators and question-paper draft/regenerate paths
  never called `check_ai_budget`/`record_ai_usage`, and the `/teacher/*` default
  rate-limit rules were absent from `Settings.rate_limit_rules`.
- **Impact:** `AI_MONTHLY_BUDGET_USD_PER_USER`, documented in `.env.example`, did
  not apply to any teacher generation path; `/admin/ai/quality` reported the
  tutor's usage while under-reporting every teacher generator run; and the five
  most expensive endpoints (`/teacher/content`, `/qpapers`, `/lesson-plans`,
  `/generate`, `/jobs`) had no per-user throttle at all.
- **Fix:** the rule set gained the teacher paths, and both generator funnels
  enforce the budget and write the ledger row.
- **Verification:** `pytest tests/test_teacher_ai_budget.py tests/test_rate_limit_coverage.py
  tests/test_product_v3.py -q` → **46 passed**; ruff and mypy clean.

### F-41 · TEST-01 · P3 · Suite determinism depends on machine speed — OPEN (pre-existing on `main`)
- **Evidence (execution):** a full local run on the rebased base finished
  `1 failed, 950 passed, 6 skipped`; the single failure
  (`tests/test_chat_history_crud.py::test_message_search_finds_own_history`,
  step "too-short queries are rejected") **passes in isolation** (`6 passed`,
  9.29s) and passes on the slower local runs.
- **Mechanism (source):** the API's limiter is a per-process in-memory sliding
  window over a 60-second horizon (`ratelimit.py:28-48`), and the rule set
  includes a generic `/tutor` ceiling of 60 requests per minute per IP
  (`config.py:119-120`). The whole suite shares one process and one
  `TestClient` IP, so a fast machine can push more than 60 `/tutor/*` requests
  through a single window and a legitimate assertion receives a 429.
- **Impact:** a false red on fast runners (and, in CI, a re-run lottery). It is
  not a product defect — production clients are not a single IP issuing 60
  tutor calls a minute from one process.
- **Recommendation:** reset/scope the limiter per test (a conftest fixture that
  clears `MemoryRateLimiter` state between tests, or a per-test key), which
  makes the suite deterministic without weakening any assertion. Not changed
  here: it touches shared test infrastructure late in this branch, and the
  assertion itself is correct.
