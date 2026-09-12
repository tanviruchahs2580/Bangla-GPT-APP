# Final Report — Purpose Review, Enterprise/National-Scale Parameter Execution & Full QA

**Date:** 2026-09-03 · **Role:** Senior full-stack engineer (agency engagement) · **Base:** release `v0.4.0` (commit `40f2ff9`)
**Constraint honoured:** NO git commit, NO push, NO CI/CD execution — all work verified live in the local working tree (16 modified files, 1 deleted, 2 new test files; ready for the owner's own commit).

---

## 1. The app's goal, scale, focus and users (established from codebase evidence)

| Question | Answer (evidence) |
|---|---|
| **Problem it solves** | Bangla-medium students (NCTB curriculum) get AI answers that are hallucinated, English-first, and invisible to parents. This app answers **only from textbook content** with provenance, in Bangla, with guardian/teacher oversight. |
| **Goal** | A trustworthy, textbook-grounded AI tutor: every answer carries a "পাঠ্যবই-সমর্থিত" (textbook-backed) badge + chapter/section citations or an explicit refusal (`insufficient_evidence`) — never invented content. |
| **Users** | Students (classes 6–10; primary), parents (invite-code linked progress), teachers (roster/analytics/assign quizzes), admins (users/analytics/retention). |
| **Scale target** | **National (Bangladesh)**: NCTB corpus classes 6–10, Bangla-first i18n (bn default), mobile bottom-nav UI for Android phones, PWA offline intent, self-hostable Docker stack (GHCR + compose profiles incl. monitoring/backup), school-NAT-friendly per-user rate limits, capacity plan (2 workers ≈ 120 concurrent journeys, runbook §10). |
| **Focus** | Chat-first tutoring (SSE), grounded Learn reading, quizzes with honest scoring, parent visibility, child-safety screening + consent evidence. |

## 2. Audit review → the efficiency parameters that matter at national scale

The prior audit produced 40+ findings. Filtered by "does this affect whether the app serves its purpose for millions of Bangla-medium students on low-end devices and intermittent connectivity", these parameters were selected for execution (P1–P11). Deliberately deferred (need git/GitHub changes — see §6): branch protection, Dependabot, CI hardening, main.py router split, lockfiles.

**Purpose check before fixes:** the core purpose (grounded tutoring) worked, but two defects directly undermined it — quizzes ignored the user's chosen subject (a student selecting গণিত got science questions), and failed LLM turns persisted orphan user messages (corrupting chat history). Both violate "serves its purpose" and were fixed first.

## 3. Improvements executed (all verified functional)

| # | Parameter (why it matters at scale) | Change | Verification |
|---|---|---|---|
| **P1** | **Quiz subject correctness** — wrong-subject quizzes directly defeat the learning purpose | `QuizPage.tsx`: controlled subject select wired into the quiz request | Browser: selected গণিত → quiz served a class-6 **mathematics** question; DB attempt row `subject='mathematics'`; new vitest regression test asserting the posted subject. **7/7 FE tests green** |
| **P2** | **Deployability** — `.env.example` was broken (`ALLOW_DIRECT_PARENT_LINK=false1440`, empty `INVITE_TTL_MINUTES`) and blocked every fresh environment bring-up | Fixed both lines; documented `TRUST_PROXY_HEADERS`; new test parses the template into `Settings` and asserts values | `test_env_example_values_boot_a_valid_settings` green |
| **P3** | **Offline resilience (PWA)** — `sw.js` shipped but was never registered; offline claim was dead code for a connectivity-poor market | `main.tsx` registers `/sw.js` in production builds only (dev-safe, no HMR breakage) | On `vite preview` (production build): `navigator.serviceWorker` registration **ACTIVE** at `/sw.js`; app renders normally |
| **P4** | **Bandwidth/device cost** — ~1.2 MB of dead KaTeX fonts + unused deps (react-markdown, remark-math, recharts) shipped to every low-end phone; 478-LOC orphaned dashboard | Deleted orphan `StudentDashboard.tsx`; removed 4 deps + katex CSS import + dead `.katex` styles + dead `meCache`; aligned manifest colors to brand tokens | `dist/` reduced **2.2 MB → 1.03 MB** (−53%); font files 65 → 24; `tsc && vite build` clean |
| **P5** | **SSE cancellation** — tutor streams were uncancellable, leaking connections on navigation (mobile data waste) | `postStream` accepts `AbortSignal`; AITutorPage aborts on unmount; AbortError handled silently | Code verified; stream flow re-tested live end-to-end |
| **P6** | **Data integrity** — user message was committed *before* the LLM call; a provider failure left an orphan turn in history (both chat endpoints) | Both endpoints now `flush()` and commit user+assistant atomically; rollback on failure paths | 2 new tests: failed `ask` and failed `ask_stream` leave **zero** persisted messages; live: successful stream persisted both turns |
| **P7** | **Privacy/PII** — `/events` logged arbitrary client `props` values verbatim (schema docstring promises "never PII") | Logs now record prop **keys only**, never values | New test + live: `{"props_keys": ["chapter","phone"]}` — phone value `01711000000` absent from log |
| **P8** | **Correct rate limiting behind a proxy** — national-scale deployments sit behind Caddy/nginx; without XFF support every user shares the proxy IP (one limit for the whole country) | `TRUST_PROXY_HEADERS` setting (default false, spoof-safe) + `_client_ip()` in the limiter middleware | New test: two spoofed X-Forwarded-For identities get independent budgets; 11th request from IP-A → 429 while IP-B passes |
| **P9** | **Memory bounds** — in-memory rate limiter was an unbounded `dict` of deques (OOM risk under millions of unique IPs) | `MemoryRateLimiter(max_keys=10_000)` evicts stale, then least-recently-hit keys | New test: 500 distinct keys bounded to 50; fresh keys still served |
| **P10** | **LLM latency/cost** — a new `httpx.AsyncClient` (connection pool) was created per request | One pooled client per provider instance + `aclose()` wired to app shutdown | All 14 provider/stream tests green; mypy clean |
| **P11** | **Error UX consistency** — Teacher/Parent/Admin dashboards leaked raw English `err.message` into the Bangla UI | All error surfaces now use the `friendlyError` pipeline (Bengali copy with actions) | Build clean; consistent with login/quiz error paths verified in browser |

## 4. Full QA — every parameter functional (final condition)

| Gate | Result |
|---|---|
| Backend: `ruff check` + `ruff format --check` | PASS |
| Backend: `mypy src` | PASS (44 files, 0 issues) |
| Backend: `pytest -q` | **171 passed, 3 skipped** (was 165; +6 new hardening tests, 0 regressions) |
| Backend: pip-audit | 0 known vulnerabilities (unchanged deps) |
| Frontend: `vitest run` | **7/7 passed** (incl. new quiz-subject regression test) |
| Frontend: `npm run build` (tsc + vite) | PASS; dist −53% (1.03 MB) |
| Live: API `/health` `/ready` | `v0.4.0`, provider=mock, ok |
| Live: SSE tutor chat (conversation → stream → badge → sources → feedback) | PASS (conversation 3, both messages persisted) |
| Live: quiz with subject selection → correct-subject attempt | PASS (mathematics) |
| Live: PWA SW active on production build | PASS (`/sw.js` ACTIVE) |
| Live: events PII scrub | PASS (keys only in logs) |
| Live: load probe (c=1,5) | 0% errors, p95 17.7→39.6 ms |
| Constraint: git commit / push / CI-CD | **NONE performed** — changes live uncommitted in the working tree |

## 5. Verdict

**Every executed parameter is functional; the app now serves its stated purpose correctly at the tested surface.** The purpose-blocking defects (wrong quiz subject, orphan chat turns, dead PWA, broken env template, raw-English errors) are fixed with regression tests; payload cut by half; privacy and proxy-scale limits hardened.

## 6. Deferred items — require git/GitHub operations (blocked by this task's constraint)

1. **Commit + push** the 20-file change set (1 deleted, 16 modified, 3 new), then let GitHub CI run — all gates were validated locally, so CI is expected green.
2. **Repository ops:** branch protection with required checks (needs public repo/Pro plan), `dependabot.yml` + alert enablement, `DEPLOY_ENABLED` var + `production` environment to activate the deploy job.
3. **Larger refactors (next release):** split `main.py` (1,793 lines) into routers, extract the 3× duplicated progress analytics, unified error-code contract (8 coded vs raw-string errors), FE ESLint/Prettier, pytest-cov coverage reporting, Playwright e2e, Python lockfile.
4. **Owner gates (unchanged):** real Gemini key validation, NCTB rights, domain/TLS/SMTP, human UAT.

*Report file is untracked by design (no-commit constraint). Live stack left running: API :8000 (v0.4.0 + improvements), web :5173 (dev), preview :4174 (production build with active SW).*
