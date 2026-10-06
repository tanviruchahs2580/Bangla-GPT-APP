# Codebase + GitHub + Live Deployment Full Audit Report

**Date:** 2026-09-03
**Auditor Role:** Senior Staff Engineer + Lead QA
**Scope:** Read-only (UI/UX & behaviour fully locked — no changes proposed or performed)
**Sources:** Codebase (FastAPI backend `apps/api`, React/Vite frontend `apps/web`) + GitHub repository (`tanviruchahs2580/Bangla-GPT-APP`, all 40 commits / 63 Actions runs / settings APIs) + Live deployment. **Note:** No Vercel deployment exists (no `vercel.json`, no `.vercel`, GitHub Deployments API empty, GitHub Pages 404). The deployment surface is GHCR/Docker (`release.yml`) plus the currently-running local live stack (`:5173`/:8000), which was used for runtime observation and is labelled as such throughout.

---

## 1. Executive Summary

### Overall health score: **56 / 100**

| # | Dimension | Score |
|---|---|---|
| 1 | Architecture & Code Organisation | 5.5/10 |
| 2 | UI / Presentation Layer (locked surface, internal quality) | 7/10 |
| 3 | State Management & Data Flow | 5.5/10 |
| 4 | API / Data / Backend Integration Layer | 6/10 |
| 5 | Performance & Runtime Quality | 5.5/10 |
| 6 | Testing Strategy | 5.5/10 |
| 7 | Type Safety, Linting & Static Analysis | 5.5/10 |
| 8 | Security & Compliance | 6.5/10 |
| 9 | Developer Experience & Maintainability | 5/10 |
| 10 | GitHub Repository Health | 3/10 |
| 11 | Live Deployment Review (Vercel: N/A → local/GHCR substitute) | 5/10 |

### Top 5 Critical / High findings

1. **HIGH — `.env.example` is actively broken.** Line 58 contains `ALLOW_DIRECT_PARENT_LINK=false1440` (mangled bool) and line 56 `INVITE_TTL_MINUTES=` is empty; copying the template crashes boot with a pydantic validation error. The regression test (`apps/api/tests/test_env_example.py:23-28`) checks only key *presence*, never values — which is why CI passes despite this.
2. **HIGH — PWA is dead code.** `apps/web/public/sw.js` implements a sensible cache strategy and `manifest.webmanifest` is valid, but `navigator.serviceWorker.register(...)` appears nowhere in `src/` or `index.html` (grep: zero hits). Live confirmation: `navigator.serviceWorker.controller === false` on the running app. Offline capability documented in README/docs is not real.
3. **HIGH — Frontend test coverage is minimal.** 6 unit tests (2 files) for 15 routes; `api.ts` itself (error parsing, 401 exemptions, SSE parser), all five dashboards, the tutor SSE stream, quiz flow, and `RequireAuth` role guards are untested. No e2e/Playwright, no visual regression, no coverage tooling. Backend testing (139 tests, hermetic, golden-eval CI gate) is far stronger — the imbalance hides regressions in exactly the layer the product shows users.
4. **HIGH — GitHub collaboration-protection layer is absent.** Branch protection on `main` is **plan-blocked** (private repo, free plan — API returns 403 "Upgrade to GitHub Pro…"), Dependabot alerts are disabled (`/vulnerability-alerts` → 404), `automated-security-fixes: {"enabled": false}`, no `.github/dependabot.yml`, no CODEOWNERS (404), no issue/PR templates. **0 PRs, 0 merge commits, 0 issues** — all 40 commits are direct pushes to `main` by the single owner.
5. **HIGH — The production deploy path has never run.** `release.yml`'s deploy job is gated on `vars.DEPLOY_ENABLED == 'true'` + a `production` environment, but the Actions Variables API returns `{"total_count":0}` and Environments API `{"total_count":0}`. The deploy job (with its auto-rollback logic) is unexercised code; all deployment evidence in docs traces to local/manual runs.

Additional High-severity internal defects observed (behaviour-level, recorded only): `QuizPage.tsx:41` always posts `subject: SUBJECTS[0].value` while the subject `<select>` (`:180-187`) is uncontrolled — the user's subject choice is silently ignored; `send_chat_message` commits the user message *before* the LLM call (`main.py:919`) and the `rollback()` on `ProviderError` (:928) cannot undo it, leaving an orphan user message on provider failure.

### Top 5 strengths

1. **CI is genuinely comprehensive** (`.github/workflows/ci.yml`): ruff check + format, mypy, pytest on Python 3.11 & 3.12, pip-audit gate, alembic up→down→up cycle, Postgres-16 service job, golden retrieval benchmark with a grounded-accuracy gate (exit 1 < 0.90), vitest, `tsc && vite build`, Docker build with Trivy HIGH/CRITICAL gate + `/health` + `/ready` container smoke. 87.3% run success (55/63); zero failures since 2026-08-26 (~18 consecutive green).
2. **Backend test discipline**: 139 test functions across 26 files; `conftest.py` autouse-nulls `env_file` for hermeticity; tmp-path SQLite isolation in 18 files; Gemini tested via `httpx.MockTransport`; injection-guard regression tests with poisoned chunks; SSE event frames asserted.
3. **Security engineering is largely strong**: PBKDF2-SHA256 200k iterations with per-hash salt and `compare_digest`; JWT HS256 with pinned algorithms and DB-role re-derivation; production boot guard (`main.py:154-180`) refusing default secrets/weak admin creds/in-memory DB; single-use SHA-256-hashed tokens; fail-closed rate limiter; evidence-tag escaping; zero raw SQL (`sqlalchemy.text()` grep: 0).
4. **Frontend runtime design quality**: 75 design tokens (`styles.css:6-76`) with full dark-theme override and pre-paint theme/lang restore (`index.html:19-29`); all 13 routes lazy-loaded with verified per-route chunks; **zero `any`** in `src/`; compile-time bn/en i18n key parity (`i18n.ts:121-123`); typed error pipeline (`ApiError` + `friendlyError`).
5. **Operational documentation is real**: `docs/runbook.md` (9 KB) covers dev→deploy→migrations→backup/restore→alerts→rotation→rollback with a dated restore rehearsal (2026-08-26, "integrity_check: ok"); `release.yml` contains working auto-rollback logic; `LAUNCH_READINESS_CHECKLIST.md` honestly leaves owner gates unchecked.

### Immediate risk summary (observations only)

- Regressions in the frontend (the locked user-facing surface) can land undetected: near-zero FE tests + no branch protection + direct-to-main pushes.
- The `.env.example` defect will break any fresh environment bring-up that follows the documented quickstart.
- Reproducibility risk: `>=`-only Python constraints with **no lockfile** (no requirements.txt/uv.lock); Docker builds install at image-build time.
- Supply-chain surface: GitHub Actions pinned by tag (not SHA); `aquasec/trivy:latest` floating tag; `appleboy/ssh-action@v1.2.0` (highest-value target) tag-pinned; Dependabot off means dependency advisories accumulate silently.
- Performance ceilings in the backend for real corpus scale: per-worker in-memory BM25 rebuild at boot, O(N) trigram fallback scan, N+1 query patterns, unbounded memory rate-limiter, no `X-Forwarded-For` handling behind a proxy.

---

## 2. Detailed Findings by Dimension

### 2.1 Architecture & Code Organisation
- **Best Practice Compliance:** Partially Applied
- **Score:** 5.5/10
- **Evidence:** `apps/api/src/bangla_gpt_api/main.py` is **1,793 lines** containing 40 routes, 6 hand-rolled middleware classes (`:183-278`), production guard (`:154`), admin bootstrap (`:355-375`), auth dependencies (`:403-442`), GDPR deletion and analytics — zero `APIRouter` usage, no routers/repositories layer, SQLAlchemy queries inline in handlers. `canonical_subject` duplicated with different semantics (`main.py:122` vs `services/learn.py:63`); progress/analytics aggregation copy-pasted 3× (`main.py:1313-1364`, `:1404-1453`, `:1724-1788`). Positive: app factory with injected `Settings` (used by ~12 test files), protocol-based LLM provider (`providers/base.py:13`), `Annotated` DI aliases, pluggable rate-limiter Protocol (`ratelimit.py:22`). Frontend `src/` is 4,877 LOC with clean small modules — but `pages/StudentDashboard.tsx` (478 LOC) is **orphaned dead code** (sole reference is its own export; `main.tsx:16-32` lazy-loads only `pages/student/*`), and `api.ts` (258 lines) mixes fetch client + auth + token storage + SSE parser + catalog endpoints.
- **Gaps & Missing Points:** no router/service/repository layering in API; duplicated analytics logic; function-level imports to break cycles (`services/tutor.py:155,206`; `ratelimit.py:69-73`); `evaluation/runner.py` near-dead (only a script and one test use it; the CI golden gate reimplements its own loop); frontend has no hooks/ layer and two coexisting markup generations (UI primitives vs raw `className` markup in Teacher/Parent/Admin dashboards).
- **Risks if left unaddressed:** every behaviour-preserving refactor of API behaviour risks regressions in the 3× duplicated analytics logic; `main.py` size makes locked-behaviour changes high-friction and review-unsafe.
- **Severity:** High

### 2.2 UI / Presentation Layer (locked surface — internal quality only)
- **Best Practice Compliance:** Partially Applied
- **Score:** 7/10
- **Evidence:** Design tokens: 75 CSS custom properties in `:root` (`styles.css:6-76`), dark theme override `:78-110` with `color-scheme: dark`; pre-paint inline script (`index.html:19-29`) prevents FOUC. 1,119-line single stylesheet in 27 commented sections; lucide icons with `aria-hidden` in 6 files; ~100 `style={{}}` occurrences (mostly token sugar, some hardcoded `rgba(255,255,255,0.15)` at `HomePage.tsx:36,39`); list keys mostly stable ids, index keys in a few static lists (`QuizPage.tsx:86,134`, `LearnPage.tsx:166`); PWA manifest present but `theme_color: #0f6b4f` (green) conflicts with `index.html:11` `theme-color: #4353b8` (indigo) and `--brand`.
- **Gaps & Missing Points:** SW never registered (see Exec. Summary #2); manifest color/value drift vs tokens; only 3 media queries in the stylesheet (min-width:760px, max-width:480px, prefers-reduced-motion); two markup generations coexist.
- **Risks if left unaddressed:** the visual system is defined in one stylesheet and token set — future changes to locked UI have a single point of coordination, and the undocumented color drift can propagate into system updates.
- **Severity:** Medium

### 2.3 State Management & Data Flow
- **Best Practice Compliance:** Partially Applied
- **Score:** 5.5/10
- **Evidence:** `QueryClient` configured once (`main.tsx:34-42`: staleTime 30s, retry 1, no window-focus refetch); only **5 `useQuery` usages, 0 `useMutation`, 0 `invalidateQueries`**; Teacher/Parent/Admin dashboards bypass react-query entirely (`useCallback + useEffect + Promise.all` — `TeacherDashboard.tsx:19-34`, `ParentDashboard.tsx:16-34`, `AdminDashboard.tsx:18-34`). `AuthContext` value not memoized (`AuthContext.tsx:36`); `api.ts` `meCache` is written by `fetchMe` but its reader `cachedMe()` has **zero call sites** (dead duplicate source of truth); `AppShell` `force()` subscription (`:48-49`) is redundant since language/theme switches reload the page (`navigate(0)` at `AppShell.tsx:81`, `MePage.tsx:112,124`). **Functional state defect:** `QuizPage.tsx:41` always sends `subject: SUBJECTS[0].value`; the subject select (`:180-187`) is uncontrolled with no `onChange`.
- **Gaps & Missing Points:** no mutation/invalidation layer; three data-fetching styles coexist (RQ, manual effects, dead code); no key factory; SSE updates unmounted component state (no cancellation — see 2.4).
- **Risks if left unaddressed:** data-flow semantics differ per page, making locked-UI refactors non-mechanical; the quiz subject defect shows state-flow divergence already escapes to behaviour.
- **Severity:** High (quiz defect) / Medium (architecture)

### 2.4 API / Data / Backend Integration Layer
- **Best Practice Compliance:** Partially Applied
- **Score:** 6/10
- **Evidence:** Backend error model is bimodal — machine codes for 8 cases (`email_taken` :554, `bad_credentials` :673, `llm_unavailable` :790, `invalid_invite` :1671, …) vs raw strings elsewhere ("Current password is incorrect" :762, "Insufficient role" :435) — so the frontend `friendlyError` pipeline cannot reliably branch. 27 of 40 routes declare `response_model`; `/feedback`, `/events`, parent endpoints return untyped dicts; `DataExportResponse` is `dict`-typed (`schemas.py:131-137`). Provider resilience is good: 30s timeout, 2 retries on `{408,429,500,502,503,504}` with capped backoff (`gemini.py:152-157`), `ProviderError` → controlled 502. SSE (`main.py:955-1019`) hand-rolls frames, handles errors as events, guards missing final event — but no heartbeat/`retry:` and it runs under 5 stacked `BaseHTTPMiddleware` layers. Pagination only on `/admin/users`; `/teacher/students` unpaginated; `/tutor/conversations` hard-capped at 100 (`:844`). Frontend: typed `ApiError` + `parseDetail`; `AUTH_401_PATHS` exemption with rationale (`api.ts:35-37`); **zero `AbortController`/`signal`/`AbortSignal` in `src/`** — SSE streams cannot be cancelled, `postStream` bypasses the shared error/401 contract and returns `done as T` unchecked (`api.ts:142`); `localStorage['bgpt_token']` = full XSS-read surface; three dashboards surface raw English `err.message` to users instead of `friendlyError`.
- **Gaps & Missing Points:** inconsistent error contract; partial response-model coverage; no request cancellation/timeout on the frontend; token expiry not tracked client-side.
- **Risks if left unaddressed:** any API-error-contract evolution will silently break dashboards that bypass `friendlyError`; uncancellable streams leak connections on navigation.
- **Severity:** High (bimodal errors + orphan-message defect) / Medium (rest)

### 2.5 Performance & Runtime Quality
- **Best Practice Compliance:** Partially Applied
- **Score:** 5.5/10
- **Evidence (code):** BM25 index rebuilt synchronously in memory **per worker at boot** (`bm25.py:47-55`, built in `create_app` at `main.py:341-349`; Dockerfile runs gunicorn `WEB_CONCURRENCY` workers → N corpus copies in RAM); trigram fallback computes Jaccard over **every** filtered chunk per query (`bm25.py:77-82`); N+1 patterns: message counts loop (`main.py:849-860`), per-student attempt loops (`:1372-1395`), `admin_overview` loads all users (`:1506`); new `httpx.AsyncClient` per LLM call (`gemini.py:128-129`); `learn.py` re-parses corpus markdown per request. Frontend: verified route-level chunks in `dist/` (main bundle 239 KB, CSS 51 KB, per-page 4.5–9.5 KB), but `katex/dist/katex.min.css` (`main.tsx:10`) ships **~65 font files ≈ 1.2 MB** in dist for math rendering that never happens (no katex/markdown JS imported); 16 font files (~500 KB) mitigated by `unicode-range` subsetting; per-SSE-token `setMessages` array copy (`AITutorPage.tsx:86-93`).
- **Evidence (live, local stack — not Vercel):** login page navigation: DCL ≈ 421 ms, load ≈ 425 ms, 34 resources (localhost transfer sizes unrepresentative); no runtime error boundary triggered; `/health` round-trip p95 9–167 ms at c=1–20 under the repo's own probe (0% errors with limits raised; 429s correctly returned at default limits).
- **Gaps & Missing Points:** no Core Web Vitals/Lighthouse measurement exists anywhere (tooling absent — see Limitations); no bundle budget; k6 scripts exist (`load/`) but are manual-run, not CI-gated.
- **Risks if left unaddressed:** retrieval latency will scale quadratically with the real NCTB corpus; boot rebuild × workers multiplies memory; the 1.2 MB dead font payload ships to every user.
- **Severity:** High (retrieval scale) / Medium (payload, N+1)

### 2.6 Testing Strategy
- **Best Practice Compliance:** Partially Applied (backend) / Missing (frontend, e2e)
- **Score:** 5.5/10
- **Evidence:** Backend: 139 functions / 26 files; hermetic (`conftest.py:15-19` nulls `env_file`); tmp-path isolation in 18 files; Postgres smoke gated to CI's PG-16 job; golden-eval as CI accuracy gate (`scripts/evaluate_golden.py:111-114`); injection-guard, SSE-frames, ratelimit fail-open/closed tests. Frontend: **6 tests / 2 files** for 15 routes; `login.test.tsx` mocks the entire `../api` module so `api.ts` itself never executes in tests. Absent everywhere: e2e (Playwright), visual regression, coverage tooling (no pytest-cov/c8 config), mutation testing, load gates in CI, tests for the quiz-subject path, orphan-message path, `/events` props logging.
- **Gaps & Missing Points:** FE regression risk on the locked surface; no contract tests between FE `types.ts` and BE schemas.
- **Risks if left unaddressed:** exactly the layer that is user-locked is the least protected; the golden gate protects retrieval accuracy but no equivalent exists for UI behaviour.
- **Severity:** High

### 2.7 Type Safety, Linting & Static Analysis
- **Best Practice Compliance:** Partially Applied
- **Score:** 5.5/10
- **Evidence:** Backend: `ruff select = ["E","F","I","UP","B"]` (no ANN/S/RUF); mypy **not strict**, `ignore_missing_imports = true`; no `py.typed`; but only 7 `Any` occurrences, 1 `type: ignore`, 5 casts in 44 files — clean baseline. Pydantic v2 idiomatic (`model_validator(mode="after")` at `schemas.py:85-91`). Frontend: `tsconfig` strict + noUnusedLocals/Parameters, `isolatedModules`, zero `any`; missing `noUncheckedIndexedAccess`, `verbatimModuleSyntax`. **No ESLint, no Prettier, no EditorConfig anywhere in the repo** (find: zero hits); `package.json` has no lint/test/typecheck scripts.
- **Gaps & Missing Points:** strictness flags off; no FE lint; untyped dict responses at API boundary.
- **Risks if left unaddressed:** style/quality drift invisible in CI; `Dict`/schema drift between FE and BE undetected until runtime.
- **Severity:** Medium

### 2.8 Security & Compliance
- **Best Practice Compliance:** Mostly Applied (backend) / Partially (dependencies, headers)
- **Score:** 6.5/10
- **Evidence:** Strong: PBKDF2-SHA256/200k (`auth/security.py:11-32`); pinned `algorithms=["HS256"]`; role always re-derived from DB; production boot guard; verification/reset/invite tokens stored as SHA-256 hashes, single-use, expiring; enumeration-safe `/auth/forgot` (always 202); reset tokens logged only in non-production with explicit comment (`main.py:732-734`); zero raw SQL; last-admin protections; `rate_limit_fail_open: false`. Weak points observed: **Dependabot disabled** (alerts 404, auto-fixes `enabled:false`, no config file); pip-audit clean at audit time but no lockfile; `/metrics` unauthenticated (`main.py:543-545`); `/events` logs arbitrary client `props` verbatim (`main.py:1047-1057`) despite schema docstring claiming "never PII" (`schemas.py:67`); rate limiter memory backend is unbounded `defaultdict(deque)` (`ratelimit.py:28-40`) with **no X-Forwarded-For handling** (all clients share proxy IP behind Caddy); `BodySizeLimitMiddleware` trusts `Content-Length` only (`:252-253`); CORS added first → innermost, so rate-limited preflights return 429 without CORS headers; security headers are only nosniff/XFO/Referrer-Policy — **no CSP, no HSTS at app layer** (API live headers verified: exactly those three + x-request-id; `apps/web/deploy/nginx.conf:9-11` adds the same three, no CSP); localStorage token XSS-read surface on the FE.
- **Gaps & Missing Points:** none of the above is currently exploitable per available evidence, but the aggregate widens attack/misconfiguration surface.
- **Risks if left unaddressed:** advisory exposure without Dependabot; proxy-deployed IP limits become global limits; PII can flow into logs via `/events`.
- **Severity:** High (Dependabot off, PII logging path) / Medium (headers, limiter bounds, metrics)

### 2.9 Developer Experience & Maintainability
- **Best Practice Compliance:** Partially Applied
- **Score:** 5/10
- **Evidence:** README accurate on CI/CD table and quickstart (Windows-only commands; quickstart says `apps/api/.venv` while the actual dev venv is the repo-root `.venv`); `.env.example` actively broken (Exec #1) and enforced by a presence-only test; `docs/API.md` is 84 lines for 40 endpoints (thin vs README's "Full reference" claim); docs/ carries 19 files of which **10 are overlapping `FINAL_*`/`*_AUDIT*` reports** (7 in docs/ + 3 at root) — signal-to-noise problem; missing CONTRIBUTING.md, CHANGELOG.md, SECURITY.md, ADRs; no `[project.scripts]`; no Python lockfile (>= only, pip install at Docker build); frontend has no lint/test scripts; no monorepo root package.json; positive: Dockerfile non-root + healthcheck + `--max-requests`, `npm ci` in CI+Docker.
- **Gaps & Missing Points:** onboarding friction (broken env template, venv mismatch), no dependency lockfile for reproducible builds.
- **Risks if left unaddressed:** fresh-environment bring-up fails; unreproducible builds complicate every future locked-UI refactor verification.
- **Severity:** High (broken env template) / Medium (rest)

### 2.10 GitHub Repository Health
- **Best Practice Compliance:** Missing (protection/collaboration) / Partially (history hygiene)
- **Score:** 3/10
- **Evidence:** private repo, 1 contributor, created 2026-08-25, 40 commits, MIT license, description stale ("foundation phase" at v0.4.0), no topics, no homepage; branch protection **unavailable** (403 plan-gated — documented, not assumed); CODEOWNERS 404; Dependabot config/alerts/auto-fixes absent/disabled; secret scanning unavailable (plan-gated); **0 PRs (all pushes direct to main), 0 merge commits, 0 issues, no issue/PR templates, no GitHub Releases** (3 tags: `v0.1.0-rc1`, `v0.2.1`, `v0.4.0`; v0.3.0 skipped — v0.3 shipped inside v0.4.0's commit). Positive: **40/40 commits follow Conventional Commits**; noreply author email; local `main` == `origin/main`.
- **Gaps & Missing Points:** no required checks/reviews possible under current plan/visibility; no release notes; no SECURITY.md.
- **Risks if left unaddressed:** nothing prevents an unverified push from reaching the published GHCR tag path; advisory silence; no audit trail via reviews.
- **Severity:** High

### 2.11 Live Deployment Review
- **Best Practice Compliance:** Not Applicable (Vercel) — Partially Applied (GHCR/Docker pipeline as deployed)
- **Score:** 5/10 (substitute surface)
- **Evidence:** No Vercel deployment exists (checked `vercel.json`, `.vercel/`, repo grep, GitHub Deployments API → empty, Pages API → 404). Actual deployment surface: `release.yml` → GHCR images `ghcr.io/tanviruchahs2580/bangla-gpt-app/{api,web}:v0.4.0+latest` (publish run **33676585125 = success**, digests logged) → deploy job **skipped** (`DEPLOY_ENABLED` var absent, `production` environment absent — verified via Actions APIs). Live observations on the running local stack: `/health` = `{"status":"ok","version":"0.4.0"}` (matches HEAD `40f2ff9` + pyproject + package.json — version parity achieved at v0.4.0); API response headers exactly `x-request-id`, `x-content-type-options: nosniff`, `x-frame-options: DENY`, `referrer-policy: no-referrer` (matches `SecurityHeadersMiddleware`); web dev server sets no-cache (dev-representative only); page renders with no error-boundary activation; `navigator.serviceWorker.controller === false` (live confirmation of the unregistered SW); admin UI displays the purge result as raw JSON string (cosmetic observation). No discrepancy found between codebase and live behaviour on the tested surface; the production nginx layer (`deploy/nginx.conf`: SPA fallback `try_files`, static `Cache-Control: public`, same three security headers) was verified at config level only, not against a running production container.
- **Gaps & Missing Points:** no production environment exists to observe; no Lighthouse/Web Vitals/CrUX data anywhere; environment separation (preview vs production) does not exist; caching/CDN/edge configuration cannot be assessed.
- **Risks if left unaddressed:** the deploy path (including auto-rollback) remains unexercised; production-only failure modes (TLS, proxy headers, gzip/brotli, real CDN caching) are unverified.
- **Severity:** High (unexercised deploy path) / Info (Vercel N/A)

### 2.12 Overall Best-Practice Compliance Scorecard
- **Best Practice Compliance:** Partially Applied
- **Score:** 56/100 (weighted toward Security & Testing)
- **Evidence:** table in Executive Summary; per-dimension scores above.
- **Gaps & Missing Points:** the two ends of the stack diverge sharply — backend engineering culture (tests, security, CI) vs frontend and repository-management hygiene.
- **Risks if left unaddressed:** composite risk concentrates on the locked UI layer (least tested, least protected path to production).
- **Severity:** High (aggregate)

---

## 3. Gap Analysis Matrix

| Area | Current State | Best Practice Target | Gap Size | Priority |
|---|---|---|---|---|
| Env template correctness | `.env.example:56,58` mangled values; presence-only test | Template boots a fresh env; values validated | Small | **P0** |
| FE test coverage | 6 unit tests; api.ts/guards/dashboards/SSE untested | Behaviour tests per page + api-client unit tests + e2e happy paths | Large | **P0** |
| Branch protection & reviews | 40 direct pushes to main; protection plan-blocked | Required status checks (CI jobs) + review path | Large (plan-gated) | **P0** |
| Dependabot / advisory surface | Config absent; alerts + auto-fixes disabled | dependabot.yml + alerts + security updates on | Small | **P0** |
| Production deploy path | `DEPLOY_ENABLED` unset; 0 environments; job never ran | Configured gated deploy, exercised with rollback drill | Medium | **P1** |
| API layering | 1,793-line main.py; 0 routers; 3× duplicated analytics | Router modules + service/repository split | Large | **P1** |
| Error contract | 8 coded errors vs raw strings; 27/40 typed responses; FE bypasses friendlyError in 3 dashboards | Uniform machine-code contract; typed responses; single FE error path | Medium | **P1** |
| Dead code & unused deps | StudentDashboard 478 LOC orphan; react-markdown/remark-math/recharts unused; ~1.2 MB katex fonts; dead meCache/force() | No unreachable code shipped | Small–Medium | **P1** |
| PWA wiring | sw.js + manifest shipped; registration absent | Registered SW consistent with offline claims | Small | **P1** |
| Request cancellation | 0 AbortController/timeout in FE | Cancellable fetches/streams | Medium | **P2** |
| Performance (backend retrieval) | Per-worker rebuild, O(N) trigram, N+1s, per-call httpx client | Shared index, bounded scans, pooled client | Large | **P2** |
| Lint/format (FE) | No ESLint/Prettier/EditorConfig/scripts | Configured lint + format in CI | Small | **P2** |
| State layer consistency | 5 useQuery / 0 useMutation; dashboards bypass RQ | Uniform server-state pattern | Medium | **P2** |
| Observability | /metrics open; PII-capable /events logging; no coverage metrics | Authenticated metrics; scrubbed logs; coverage % | Medium | **P2** |
| Release artefacts | 3 tags, no GitHub Releases/notes/SBOM | Release notes, SBOM/provenance, changelog | Medium | **P3** |
| Docs hygiene | 10 overlapping FINAL_*/audit reports; 84-line API.md for 40 routes | Single changelog + complete API reference | Small | **P3** |

---

## 4. Testing & QA Gaps

- **Frontend (highest risk to the locked surface):** no tests for `api.ts` (parseDetail, AUTH_401_PATHS logic, postStream parser), `AuthContext`/401-handler flow, `RequireAuth` role guards (`main.tsx:44-63`), AITutor SSE streaming UI, QuizPage start/submit (incl. the subject-selection defect), Teacher/Parent/Admin dashboards, i18n reactivity, theme/lang persistence, PWA. No Playwright/Cypress e2e, no axe-a11y tests, no visual regression screenshots, no coverage measurement.
- **Backend:** coverage is broad but unmeasured (no pytest-cov); untested paths identified: orphan-user-message on LLM failure (`main.py:919-928`), `/events` props logging, `X-Forwarded-For` behaviours, chunked-body size-limit bypass, preflight-CORS-429 interaction; no mutation testing; k6 load scripts not CI-gated; golden gate covers retrieval accuracy only (0.90 threshold), not answer quality.
- **Contract testing:** no schema-sync check between `apps/web/src/types.ts` and backend Pydantic schemas; no alembic-vs-models autogenerate diff test; no OpenAPI snapshot gate.
- **CI reliability signals:** 63 runs, 55 success / 8 failure — all 8 during 2026-08-25/26 bring-up; zero PR-triggered runs ever (0 PRs), so PR-path CI is unproven; no `concurrency: cancel-in-progress`, no `timeout-minutes`, no retry strategy for flaky steps (none observed flaky to date).

## 5. Live vs Codebase Consistency Check

Surface observed: the running local live stack (SPA :5173 + API :8000) — the only live surface available (see Limitations).

| Check | Result |
|---|---|
| Version parity | `/health` `0.4.0` == `pyproject.toml` == `package.json` == README status == HEAD `40f2ff9` — consistent (defect V7 from prior audits is closed at v0.4.0) |
| Security headers | Live API headers exactly match `SecurityHeadersMiddleware` (`main.py:258-266`); no headers beyond those three — matches code, no CSP/HSTS at app layer |
| PWA behaviour | `navigator.serviceWorker.controller === false` — consistent with code (registration never wired); contradicts docs' offline claim |
| Runtime errors | None observed: error boundary not triggered; login→student flows render; SSE chat + quiz completed in prior live session |
| Rate limiting | Live 429s observed at the documented limits (tutor 30/min/user; login 10/min/IP) — matches `config.py:50-53` |
| Admin purge | UI shows raw deletion JSON — matches `AdminDashboard` rendering of the API payload (cosmetic) |
| Quiz subject selector | Uncontrolled select vs always-posted default subject (`QuizPage.tsx:41,180-187`) — code intent and behaviour diverge (functional defect, recorded only) |
| Vercel production | **Not evaluable — no Vercel deployment exists**; no prod URL, headers, CDN, or env separation to compare |

## 6. Limitations of This Audit

1. **No Vercel deployment exists** (verified via repo config, GitHub Deployments/Pages APIs). Dimension 11 was substituted with the GHCR/Docker pipeline evidence and the running local stack; any Vercel-specific findings (edge config, serverless cold starts, preview envs) are therefore out of scope by absence, not assumption.
2. **Lighthouse / Core Web Vitals not measured** — Lighthouse tooling is unavailable in this environment, and the only live surface is a Vite dev server (not the production nginx bundle); `dist/` bundle analysis and local navigation timing were used as proxies. Production-cache/CDN behaviour unverified.
3. **Branch protection and secret scanning APIs returned 403** (private repo, free plan) — recorded as plan-gated unavailability, with the API responses as evidence. `security_and_analysis` was `null`/inaccessible.
4. **Production nginx layer** (`deploy/nginx.conf`) was assessed from configuration files, not a running production container; gzip/brotli/TLS/HSTS-at-proxy behaviour is unverified.
5. **Accessibility** was assessed statically (ARIA/semantics/focus patterns) plus DOM-level live checks; no screen-reader or axe/contrast tooling was run; color contrast not measured.
6. **LLM provider (Gemini) live behaviour** was not exercised (mock provider by design); provider cost/quota/rate-limit behaviour under real keys is out of scope.
7. GHCR package visibility/contents were verified via workflow logs (publish step success + digests); direct package API verification unavailable to the audit token (no `read:packages` scope).
8. Line numbers refer to the working tree at audit time (HEAD `40f2ff9`, 2026-09-03).

## 7. Appendix

### A. Key file/folder map
```
apps/api/src/bangla_gpt_api/
  main.py (1793 — God-module: 40 routes, 6 middleware, guards)
  config.py (94) · schemas.py (258) · ratelimit.py (78) · metrics.py
  auth/security.py (47) · db/{models.py 202, session.py}
  services/{tutor 227, quiz 220, learn 197, safety 84, mailer 44}
  providers/{gemini 206, mock 26, base 19} · retrieval/{bm25 101, hybrid 98}
  data/{loader 90, nctb_loader 149, sample_nctb/ ×11} · curriculum/ · nctb/ (~950) · evaluation/ (near-dead) · ingestion/
apps/api/tests/ (26 files, 139 tests) · alembic/versions/ (4 migrations)
apps/web/src/ (4,877 LOC)
  main.tsx (205) · AppShell.tsx (117) · AuthContext.tsx (53)
  api.ts (258) · i18n.ts (270) · errors.ts (37) · types.ts (153)
  components/ui.tsx (161) · lib/{theme 25, cn 3}
  pages/student/{AITutor 232, Quiz 202, Learn 185, Me 158, Home 146}
  pages/{StudentDashboard 478 (ORPHANED), Teacher 204, Parent 168, Admin 162, ForgotReset 140, Register 123, Legal 93, Login 85}
  styles.css (1119, 75 tokens, 27 sections) · test/ (6 tests)
.github/workflows/{ci.yml, release.yml, repository-sanity.yml}
docker-compose.yml (profiles: core/web/tls/postgres/monitoring/backup)
docs/ (19 files; 10 overlapping FINAL_*/audit reports) · scripts/ · load/
```

### B. Important GitHub links
- Repo: https://github.com/tanviruchahs2580/Bangla-GPT-APP (private, MIT)
- CI (green, 6/6 jobs): https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/runs/33676358619
- Release publish to GHCR: run `33676585125` (build-push success; deploy skipped — unconfigured)
- Tags: `v0.1.0-rc1`, `v0.2.1`, `v0.4.0` (HEAD `main` = `40f2ff9`)

### C. Performance raw notes
- Local live (dev server, unrepresentative of prod CDN): login page DCL ≈ 421 ms / load ≈ 425 ms / 34 resources.
- Bundle (production build, measured from `dist/`): `index-*.js` 239 KB (77 KB gzip), `index-*.css` 51 KB, per-route chunks 4.5–9.5 KB; ~65 KaTeX font files ≈ 1.2 MB shipped unused; 16 @fontsource files ≈ 500 KB (unicode-range subsetting).
- API probe (repo's own, local): c=1→20, 0% errors, p50 5.7→107.5 ms, p95 9.0→167.0 ms (limits temporarily raised for the pure-latency run; default limits correctly 429 beyond 30 tutor req/min/user).
- No Lighthouse/CWV data exists (tooling absent; no production URL).

### D. Dependency risk summary
- Python (pip-audit at audit time): **0 known vulnerabilities** (local editable package skipped as un-publishable). Constraints `>=`-only, **no lockfile**; resolved set: fastapi 0.141.1, pydantic 2.13.4, SQLAlchemy 2.0.52, uvicorn 0.52.4, PyJWT 2.13.0, httpx 0.28.1 (current-generation).
- npm: lockfile present, `npm ci` enforced in CI/Docker; **3 unused runtime dependencies** (react-markdown, remark-math, recharts) + CSS-only katex (1.2 MB fonts); prior audit records 0 npm prod vulns at v0.3.1 (not re-run in this audit — Dependabot disabled so no continuous signal).
- Supply-chain posture: GitHub Actions tag-pinned (`@v4`/`@v5`/`@v6`, no SHA pinning); `aquasec/trivy:latest` floating tag; `appleboy/ssh-action@v1.2.0` tag-pinned; no SBOM/provenance/attestation; Dependabot fully off.

---

*End of report. This audit makes no change recommendations; it records observed state, gaps, and risks only. Report file is untracked by design (read-only audit).*
