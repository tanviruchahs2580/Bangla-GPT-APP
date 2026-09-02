# Final CI/CD Execution Report — Release v0.4.0

**Date:** 2026-09-03 · **Executor:** ZCode (autonomous, per owner instruction) · **Repo:** github.com/tanviruchahs2580/Bangla-GPT-APP
**Verdict: RELEASE EXECUTED — all local gates green, GitHub CI green, images published to GHCR. Deploy-to-host correctly skipped (owner-gated).**

---

## 1. Executive summary

The uncommitted v0.3/v0.4 working tree (46 modified + 44 untracked files) was brought **live**, tested **end-to-end as a real user in a browser**, hardened with **5 bug fixes** (including the audit's pre-go-live P1), version-synced to **0.4.0**, gated through the **full local CI matrix (13/13 green)**, committed in **6 logical commits**, pushed to `main` (**GitHub CI 6/6 jobs green**), and tagged **v0.4.0** — which published `api` and `web` images to GHCR. The SSH deploy job was skipped because `DEPLOY_ENABLED`/SSH secrets are not configured (expected from this machine; owner-gated).

## 2. Environment & sync verification

| Check | Result |
|---|---|
| Working directory | `C:\Users\DST\projects\Bangla GPT APP` (Git repo, branch `main`) |
| Remote | `https://github.com/tanviruchahs2580/Bangla-GPT-APP.git` (fetch OK, auth OK) |
| Baseline commit / tag | `1e3c949` = `origin/main`; tags `v0.1.0-rc1`, `v0.2.1` |
| Stale processes found | Old uvicorn (Aug 30) on :8000 and old Vite (Sep 1) on :5173 serving **stale code** — killed and restarted fresh |
| Fresh DB | `live_test.db` created via `alembic upgrade head` → chain `7a826704cc96 → 19b86998e9fa → c3f4a5b6d7e8 → d4e5f6a7b8c9 (head)` |
| Live sync proof | `/openapi.json` exposes all 36 routes incl. every new v0.3 route; `/health` → `version 0.4.0` after sync; Vite serves the working tree directly |

## 3. Live user-level E2E test (real browser, Bangla UI)

All flows executed in the ZCode in-app browser against `http://localhost:5173` (API on :8000, mock LLM provider, SMTP off → codes logged).

| # | Flow (as a user) | Result |
|---|---|---|
| 1 | `/` → `/login` redirect, page render, topbar/bottom-nav | PASS |
| 2 | Login with **wrong password** | **FAIL → fixed (E2E-01)** |
| 3 | Student registration (class 6 + guardian consent) → `/student` home | PASS |
| 4 | Learn: class chips → subject grid → chapter list → chapter reader | PASS |
| 5 | AI Tutor: question → SSE streaming answer → "পাঠ্যবই-সমর্থিত" badge → source chips → thumbs feedback | PASS (answer leaked system prompt → **fixed, AUD-01**) |
| 6 | Quiz: 3-question science quiz → answer → submit → **100% result** → progress ring 0→100% | PASS (minor alt-attr bug → **fixed, E2E-02**) |
| 7 | Teacher: register → roster (2 students) → chapter-accuracy analytics → assign quiz (persists as `open` attempt) | PASS |
| 8 | Parent: register → redeem invite code `BGPT-…` → child linked → per-chapter progress | PASS (student-side generator missing → **fixed, E2E-04**) |
| 9 | Admin (bootstrap `admin@demo.com`): analytics (5 users), search, role change + revert, retention purge (returns deletion JSON) | PASS |
| 10 | Forgot → console reset code → new password → auto-login → re-login with new password | PASS |
| 11 | Language bn↔en toggle | **PARTIAL → fixed (E2E-03)** |
| 12 | Role guards (admin → `/student` bounces to `/admin`) | PASS |
| 13 | API: GDPR export, `/metrics` Prometheus, rate limits (429 after 30/min per user — correct), DB persistence (feedback/conversations/messages rows) | PASS |

Evidence screenshots: `live_evidence/01…06*.png` (local, git-ignored).

## 4. Bugs found by live testing → fixed & re-verified

| ID | Severity | Defect | Fix | Re-test |
|---|---|---|---|---|
| AUD-01 | P1 | Mock LLM echoed the **entire system prompt + raw `<evidence>`/`<user_question>` markup** to students (also stored in DB) | `providers/mock.py` now composes a clean Bengali answer quoting only retrieved evidence; system prompt never echoed. Bug-codifying test updated + new leak-guard test | Browser: answer clean, badge intact ✓ |
| E2E-01 | P1 | Failed login/verify/reset (expected 401s) triggered the global force-logout handler → page reloaded before the friendly error rendered (silent blank form) | `api.ts`: auth endpoints exempted from `onUnauthorized` (`AUTH_401_PATHS`) | Browser: "ইমেইল বা পাসওয়ার্ড সঠিক নয়।" shows inline ✓ |
| E2E-04 | P1 | Parent invite flow incomplete: ParentDashboard tells users the student "Account" page generates the code — but no such UI existed (backend `POST /students/me/invite-code` works) | Student Me page: "অভিভাবক যুক্ত করুন" card with generator (i18n bn/en); parent hint updated | Browser: generated `BGPT-B6D13AEF`, 1440-min TTL ✓ |
| E2E-03 | P2 | Language toggle updated only the topbar (AppShell subscribed); page content stayed in Bangla | Topbar toggle now remounts via `navigate(0)` (same pattern as the Me-page select) | Browser: whole page switches bn↔en ✓ |
| E2E-02 | P3 | ProgressRing `aria-label="[object Object]"` | aria-label always percentage string | DOM: `aria-label="100%"` ✓ |

## 5. Local CI gates (mirror of ci.yml + runbook SOP) — 13/13 green

| Gate | Result |
|---|---|
| `ruff check .` | PASS |
| `ruff format --check .` | PASS (84 files) |
| `mypy src` | PASS (44 files) |
| `pytest -q` | **165 passed, 3 skipped** (post-fix) |
| `pip-audit` | 0 known vulnerabilities |
| Alembic cycle (SQLite) up→down→up | PASS → `d4e5f6a7b8c9 (head)` |
| App-factory smoke | 41 routes, health 0.4.0 |
| Postgres 16 job (docker) — full alembic cycle + `test_postgres_smoke.py` | PASS |
| Golden retrieval eval | hit@3 = 1.0, grounded accuracy = 0.933 |
| `vitest run` | 6/6 passed |
| Web `tsc && vite build` | PASS |
| Docker build + container smoke (`ENV=ci` → `/health` 200, `/ready` provider=mock) | PASS (v0.4.0) |
| Load probe `scripts/concurrency_probe.py` (c=1,5,10,20 × 40 reqs) | 0% errors, p95 9→167 ms (< 300 ms SLO). Note: at default limits the limiter correctly returns 429 after 30 tutor reqs/min/user — limits temporarily raised for the pure-latency run |

(Trivy runs inside GitHub CI's docker job — passed there; not installed locally. k6 not installed → repo's own probe used, per runbook fallback.)

## 6. GitHub CI (push `main`)

Run: **[API CI 33676358619](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/runs/33676358619)** — **success**, all 6 jobs green:
Lint & test (3.11) ✓ · Lint & test (3.12) ✓ · Postgres engine check ✓ · Golden retrieval benchmark ✓ · Web build & test (incl. new vitest gate) ✓ · Docker build & container smoke (incl. Trivy HIGH/CRITICAL gate) ✓
Repository Sanity run: **success**. Commit range pushed: `1e3c949..c1e61c2`.

## 7. Commits (6 logical commits on `main`)

```
46de630 feat(api): v0.3 product features + AUD-01 fix, version 0.4.0
b8679ae feat(web): v0.4 UI — AppShell, i18n, PWA, student pages + bug fixes
292dc0d ci: vitest unit-test gate in web job; compose env for v0.3 services
309fd11 feat(ops): concurrency probe + k6 tutor load script; env examples
e66a79b docs: v0.3/v0.4 execution, validation, audit, roadmap and launch-readiness reports
c1e61c2 chore(release): README status v0.4.0; ignore local live-test evidence
```

## 8. Release: tag v0.4.0 → GHCR

- Tag `v0.4.0` pushed (`26232debfd95`).
- Release & Deploy run **33676585125**: *Build & push images to GHCR* = **success**; *Deploy to production host (SSH)* = **skipped** (`vars.DEPLOY_ENABLED != 'true'` / SSH secrets absent — owner-gated, as designed with automatic rollback available when configured).
- Images published (workflow-log verified, with digests):
  - `ghcr.io/tanviruchahs2580/bangla-gpt-app/api:v0.4.0` (+ `latest`)
  - `ghcr.io/tanviruchahs2580/bangla-gpt-app/web:v0.4.0` (+ `latest`)
- Note: GHCR packages are **private by default**; owner can flip visibility in Package settings if public pulls are wanted.

## 9. Version sync (defect V7 closed)

| File | Before | After |
|---|---|---|
| `apps/api/pyproject.toml` | 0.2.1 | **0.4.0** |
| `apps/api/src/.../config.py` (`/health`) | 0.3.1 | **0.4.0** |
| `apps/web/package.json` (+ lock) | 0.1.0 | **0.4.0** |
| `README.md` status | v0.3.1 | **v0.4.0** |

## 10. Owner-gated items (unchanged, per repo SOP) & limitations

- **Deploy to a host**: set `vars.DEPLOY_ENABLED=true` + `DEPLOY_HOST/USER/SSH_KEY` secrets; the workflow auto-deploys with health-gate rollback.
- **Real Gemini**: live testing used `LLM_PROVIDER=mock` (all functional paths exercised; answer quality with the real model remains to be validated with an owner-supplied paid key).
- NCTB real-textbook rights, domain/DNS/TLS (Caddy), SMTP, offsite backup sync, human UAT — per `docs/LAUNCH_READINESS_CHECKLIST.md`.
- Trivy/k6 are enforced/performed in CI or via repo fallbacks locally (not installed on this machine).
- Live-run artifacts (`live_test.db`, logs, `live_evidence/`) are local-only and git-ignored; test users remain in `live_test.db` only.
