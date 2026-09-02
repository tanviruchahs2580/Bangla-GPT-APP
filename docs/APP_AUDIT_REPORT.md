# BANGLA GPT APP — FULL AUDIT REPORT (based on current condition)

> Audit date: 2026-08-26 · Audited state: v0.3.1 (RC, uncommitted) · Environment: Windows 11,
> Python 3.12.10, Node 24, Docker 29.7.2 · Basis: code reading, both enterprise validation rounds,
> security/supply-chain scans, live performance probes, and a running local preview
> (`http://localhost:5173`).
> Companion docs: `FINAL_ENTERPRISE_VALIDATION_REPORT_MASTER.md`, `PRODUCTION_GRADE_ROADMAP.md`.

---

## 1. EXECUTIVE SUMMARY

**Verdict: B — production-ready backend + functional-but-MVP frontend. Not yet "international-level".**

The middleware is the strongest layer: auth/RBAC, grounding, quizzes, progress analytics,
moderation, observability, and tests are all in place and green (157 pytest, 0 ruff/mypy issues).
The frontend is fully functional and ran end-to-end in preview, but is below an international
standard on visual identity, accessibility rigor, content rendering (no markdown/math), resilience
(silent error swallowing), and automated UX/e2e testing.

**Headline numbers**

| Metric | Result |
|---|---|
| Backend unit/API tests | 157 passed / 3 skipped |
| ruff (apps+scripts) / mypy | clean / 43 files clean |
| Frontend vitest | 6 passed |
| pip-audit (Python) | 0 vulnerabilities |
| npm audit (prod / incl. dev) | 0 / 2 (esbuild dev-only, accepted) |
| bandit SAST | 0 HIGH / 0 MED / 6 LOW |
| gitleaks | 17 hits — all `generic-api-key` on test fixtures (0 real secrets) |
| Trivy container HIGH / CRITICAL | 13 / 3 (base-image layer, vendor `fix_deferred`) |
| Concurrency probe (c=1→50) | 0% errors, p50 9→377 ms, p95 ~490 ms @50 |
| Progress endpoint p95 | 33.7 ms @ 60 rows |
| Deployment rehearsal | PASS (health + business smoke 5/5) |
| Backup→restore | PASS (integrity + rows verified) |

**Blockers to public launch (all owner-owned):** real NCTB corpus rights, Gemini paid tier + key
rotation, domain/TLS/SMTP, RC commit/tag, human UAT + legal.

---

## 2. SCOPE & METHOD

- **In scope:** architecture, backend (functional/API/auth/RBAC/data/security/perf), frontend
  (UI/UX/a11y/i18n/perf/testing/observability/PWA), supply-chain, container, deployment/ops, docs.
- **Out of scope / N/A:** file uploads, webhooks, queues/workers, multi-region (not in product).
- **Methods:** source review; two validation round reports; `pytest`, `ruff`, `mypy`, `bandit`,
  `pip-audit`, `npm audit`, `gitleaks` (docker), `trivy` (docker); live `docker build/run` +
  concurrency probe; direct UI code reading (`apps/web/src/**`); running preview walkthrough.
- **Not automated (gap):** browser E2E, axe/contrast audit, k6 at staging scale, alert firing.

---

## 3. PROJECT / PRODUCT IDENTITY

- **Goal:** safe, NCTB-grounded, Bangla-first AI personal tutor (classes 1–12) with citations,
  curriculum quizzes, and progress analytics; teacher/parent/admin roles.
- **Target user:** Bangla-speaking students (mobile-first, low-end Android); secondary teachers,
  parents (consent-gated linking), admins.
- **Focus:** grounding/trust, child safety, measurable outcomes.
- **Target scale:** national; design point tens-of-thousands concurrent at peak.
- **Stack:** FastAPI/SQLAlchemy/Alembic/pytest · React 18/Vite 5/TS/vitest · SQLite | Postgres 16 ·
  Redis limiter · Caddy/nginx/Prometheus/Grafana/backup sidecar (compose profiles) · Gemini upstream.

---

## 4. ARCHITECTURE AUDIT

| Area | Assessment | Notes |
|---|---|---|
| Layering | GOOD | providers/retrieval/services separated; provider abstraction (mock vs gemini). |
| Streams | GOOD | SSE token streaming with explicit `done`/`error` events; error event not `assert`-strippable (V6). |
| State | GOOD | Stateless API; persistent DB; boot-guard refuses in-memory sqlite in prod (V8). |
| SPOFs | RISK | Single Postgres node + single Gemini upstream (mitigations: backups, retry/degrade). |
| Config | GOOD | Single `Settings` source; `.env.example` parity enforced by test. |
| Versioning | OK | Bumped to 0.3.1 (V7) but RC uncommitted/untagged. |

---

## 5. BACKEND AUDIT

### 5.1 Functional coverage — PASS
Grounded Q&A + citations, multi-turn chat + history + SSE, child-safety moderation w/ refusal
battery, quizzes (no answer leak), progress analytics (weak-chapter detection), RBAC, parent invite
link, email verify/reset/change, GDPR export/delete + consent evidence, rate limiting, admin
management + retention purge — all implemented and tested.

### 5.2 API design — PASS
24 endpoints validated: method/auth/validation/status/pagination/filtering/rate-limit/duplicate.
Consistent error envelope `{code, message}`; malformed→422, oversized→413, none→204, unknown→404.

### 5.3 Auth & RBAC — PASS
PBKDF2-SHA256 200k iters + salt; HS256 JWT ≥32-char secret enforced in prod; verification/reset
hashed single-use tokens; 4-role matrix; 19-check persona battery incl. IDOR + cross-role 403;
last-admin guard; per-user limiter prevents classroom lockout.

### 5.4 Database — PASS
9 tables + FKs + unique constraints; Alembic up→down→up clean; race regressions green
(dup-register→409, double-grade→single-winner 400).

### 5.5 Security (app) — PASS*
Redirect-injection guarded (V1), parent-IDOR closed (V2), events flood-capped (V3), prompt-
injection delimiters + poisoned-chunk test. `*` = regex moderation layer pending human red-team.

---

## 6. FRONTEND AUDIT (direct code + live review)

### 6.1 Functionality — PASS (MVP)
Chat(SSE) + grounding badge + citations, quiz, progress, account delete/export, auth flows (login/
register/forgot/reset/verify), EN/বাং switch, dark mode — all wired and working in preview.

### 6.2 Concrete code-level findings

| # | Severity | Finding | Location |
|---|---|---|---|
| F1 | MED | Silent error swallowing: `.catch(() => undefined)` on conversations + progress → backend outage looks like empty UI | `StudentDashboard.tsx:50,60` |
| F2 | MED | `<html lang>` never updated on i18n switch → EN users keep `lang="bn"` (screen-reader bug) | `i18n.ts`/`main.tsx` |
| F3 | LOW | Dead code: `t('askPlaceholder') ? 'টিউটর' : 'টিউটর'` (always 'টিউটর'); hacky `.replace(/\s*\(.*\)/)` in title | `StudentDashboard.tsx:183,178` |
| F4 | MED | No markdown/KaTeX → tutor answers render as flat text (weak for an education product) | `StudentDashboard.tsx` render |
| F5 | LOW | Emoji icons (📘👍👎🙈👁️) — not crisp, themeable, or localizable | pages |
| F6 | MED | No global toasts; errors = small inline red text; 429/network have no visible backoff UX | pages |
| F7 | MED | Delete modal: no Escape-to-close / focus trap / scroll lock | `StudentDashboard.tsx` AccountCard |
| F8 | LOW | No route lazy-loading; all pages eager | `main.tsx` |
| F9 | MED | `sw.js` registered in prod but PWA substance unverified (manifest/icons/offline strategy) | `main.tsx:163` |
| F10 | MED | No frontend error tracking / privacy analytics | — |
| F11 | LOW | Token in `localStorage` (XSS surface; acceptable at scope, note httpOnly-cookie path) | `api.ts` |
| F12 | LOW | No loading skeleton for progress/conversations (blank until data) | `StudentDashboard.tsx` |

### 6.3 Parameter scorecard

| Parameter | Grade | Evidence |
|---|---|---|
| Visual identity / branding | 5/10 | Gradient topbar, no logo/wordmark/illustrations/empty-state art |
| Design system | 6/10 | Token-based flat CSS; no component primitives/motion scale enforcement |
| Color & theme | 7/10 | Light/dark tokens; contrast not measured |
| i18n correctness | 6/10 | bn/en dict; `lang` bug (F2) |
| Typography | 8/10 | Self-hosted Bangla webfonts; scale not applied uniformly |
| Responsive | 7/10 | 760px breakpoint; mobile conv-list horizontal scroll; no tablet tier |
| Loading states | 4/10 | Missing skeletons (F12) |
| Error/resilience | 4/10 | Silent catches (F1), no toasts (F6) |
| Forms/validation | 6/10 | required/minLength only; no inline field errors/strength/confirm |
| Feedback/micro-interactions | 5/10 | Spinner+button; no toasts/success anims |
| Accessibility | 5/10 | aria-live/roles/focus-visible good; modal (F7), lang (F2), contrast unmeasured, no axe |
| Icons | 4/10 | Emoji (F5) |
| Content rendering | 3/10 | No markdown/math (F4) |
| Performance (web) | 7/10 | No lazy-loading (F8); fonts self-hosted |
| PWA/offline | 3/10 | Unverified (F9) |
| Frontend testing | 3/10 | 6 vitest; no component/a11y(e2e) |
| Frontend observability | 2/10 | None (F10) |

---

## 7. SUPPLY-CHAIN AUDIT

| Source | Result | Notes |
|---|---|---|
| Python (pip-audit) | 0 | clean |
| npm prod | 0 | clean |
| npm dev | 2 | esbuild≤0.24.2 (dev-server only, accepted) |
| gitleaks | 17 | all `generic-api-key` on `jwt_secret=test-…` fixtures; 0 real secrets |
| bandit | 0H/0M/6L | LOWs reviewed-intentional |
| Trivy image | 13H/3C | base-image layer; 13 vendor `fix_deferred`; runs non-root |

---

## 8. PERFORMANCE (measured, not estimated)

| Path | p50 | p95 | Notes |
|---|---|---|---|
| progress (60 rows) | 20.5 ms | 33.7 ms | host/SQLite |
| users/me | 13.2 ms | 22.2 ms | |
| chat turn (mock) | 35 ms | 51 ms | |
| Mix probe c=1/10/25/50 | 9/53/187/377 ms | ~15/117/380/490 ms | 0% err; DB-bound |

Bottleneck: LLM latency dominates (>90% of tutor p95). Backend scales to c=50 DB-path cleanly.

---

## 9. TESTING & QUALITY

- Backend: 157 pass/3 skip; ruff(clean) + format; mypy strict 43 files; alembic cycle; race tests.
- Frontend: 6 vitest; **gaps** = component, a11y (axe), visual regression, e2e.
- CI: 7 api jobs + web (vitest, build, docker probes). Missing: Playwright e2e, lighthouse budget.
- Reproducible build: fresh venv → 156 then 157 passed (identical).

---

## 10. DEPLOYMENT / OPS / DR

- Deployment rehearsal PASS (docker build+run, health/ready, business smoke 5/5); fail-closed
  config guard verified; rollback rehearsed (bad-config→recover).
- Backup→restore PASS (integrity + rows). `X-Request-ID` + `bgpt_*` metrics live.
- **Not itemized to production ISOLATION:** no staging k6 run, no alert-fire verification, no
  authorized host / domain / TLS / SMTP.

---

## 11. DEFECT REGISTER (cumulative, current)

Resolved V1–V6 (round 1) + V7 (version), V8 (sqlite boot-guard), V9 (probe header), V10 (script lint).
Frontend findings F1–F12 (section 6.2) are **open**, tracked in `PRODUCTION_GRADE_ROADMAP.md`
(Phases 1–7). No critical/high open backend or security findings.

---

## 12. RISK REGISTER

| Risk | Sev | Prob | Owner | Status |
|---|---|---|---|---|
| No real NCTB corpus rights | High | High | Owner | OPEN |
| Gemini key exposure/quota | High | Med | Owner | OPEN — rotate + paid |
| Domain/TLS/SMTP unprovisioned | Med | High | Owner | OPEN |
| Working tree uncommitted (RC identity) | Med | High | Owner | OPEN |
| Human UAT/legal sign-off | Med | Med | Owner | OPEN |
| Frontend UX/a11y/e2e gaps | Med | High | Agent | OPEN (roadmap) |
| esbuild dev advisory | Low | Low | Agent | ACCEPTED |

---

## 13. OVERALL SCORECARD

| Category | Score |
|---|---|
| Architecture | 8/10 |
| Backend functional/API/auth/RBAC | 8/10 |
| Backend security/data | 8/10 |
| Performance (backend) | 7/10 |
| Supply chain | 8/10 |
| Deployment/ops/DR | 7/10 |
| Frontend functionality | 7/10 |
| Frontend UI/UX & visual | 5/10 |
| Frontend a11y | 5/10 |
| Frontend testing/observability | 3/10 |
| Product value (content) | 3/10 |
| **Overall** | **6.3/10 → B** |

---

## 14. PRIORITIZED REMEDIATION (short form)

- **P0 (owner blockers):** NCTB rights → Gemini paid/rotate → domain/TLS/SMTP → commit+tag v0.3.1 → UAT/legal.
- **P1 (do first):** data layer + global toasts + kill silent catches; abortable stream (F1,F6,F12).
- **P2 (quick wins):** fix `<html lang>` + dead code; modal a11y; i18n lint (F2,F3,F7).
- **P3 (grade up):** design system + SVG icons + illustrations; markdown/KaTeX (F4,F5).
- **P4 (quality net):** jest-axe, Playwright e2e, component tests, Sentry + analytics, PWA, lazy routes (F8–F10).
- Full detail: see `docs/PRODUCTION_GRADE_ROADMAP.md`.

---

## 15. FINAL VERDICT

**B — PRODUCTION READY (backend) WITH DOCUMENTED LIMITATIONS (frontend + content).**
Safe to pilot behind the compose stack today, provided owner clears P0. Frontend is a solid MVP but
is the main distance to "international-level": resilience, visual identity, accessibility,
content rendering, and automated UX testing remain (F1–F12). No evidence supports an A rating until
real corpus + human UAT + frontend hardening are complete; no evidence warrants C/BLOCKED.
