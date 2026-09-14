# FULL QA / ENTERPRISE AUDIT — 2026-09-15

> **Scope:** app, codebase, repository structure, live deployment sync, user-journey testing.
> **Release under test:** v0.9.1 (`0c2311b` + in-flight working-tree changes, now green).
> **Policy:** no git commits, pushes or CI were executed. Container redeploy + Vercel
> redeploy were performed because "live must sync with final" was an explicit goal.

---

## 1. Verdict

**PASS — the live version is now fully in sync with the final v0.9.1 codebase, and every
functional parameter tested as a user works end-to-end.**

Three blocking defects were found and fixed during this audit (live-site 502, test
hermeticity break, insecure production boot config). All suites, lints, type checks,
builds, and vulnerability scans are green.

---

## 2. Blocking defects found & fixed

| # | Severity | Defect | Fix | Evidence |
|---|----------|--------|-----|----------|
| 1 | **P0 — live site down** | `apps/web/vercel.json` proxied `/api/*` to a dead quick-tunnel URL (`endif-bottom-inputs-pens`); every Vercel API call returned `502 DNS_HOSTNAME_NOT_FOUND` | Restarted `api-tunnel`, updated rewrite to `tablets-forecasts-designed-fair`, redeployed Vercel production | `https://bangla-gpt-app.vercel.app/api/health` → 200 `{"status":"ok"}` |
| 2 | **P0 — tests broken** | Uncommitted config change (default `DATABASE_URL` switched from in-memory to file SQLite) leaked 9 test modules that don't pass an explicit DB into a shared `./bangla_gpt.db`; full suite failed (2 failed, 4 errors) | `tests/conftest.py` now forces an in-memory DB when neither kwarg nor `DATABASE_URL` env is explicit (respects pydantic-settings precedence) | Full suite twice: **628 passed, 6 skipped, 0 failed** |
| 3 | **P0 — production security** | `api-live` ran an **old v0.8.1 image** with `ENV=ci` + the default insecure `JWT_SECRET` (`dev-insecure-change-me`, 22-byte HMAC warning in logs) while serving the public tunnel | Rebuilt `bangla-gpt-api:v0.9.1` from current source, relaunched with `ENV=production` + generated `JWT_SECRET` (48-byte urlsafe), `PII_ENC_KEY` (Fernet), `METRICS_TOKEN`, `ALLOWED_ORIGINS` allowlist, admin credentials, and SMTP via a new `api-mailpit` container | `/api/metrics` → 403 to anonymous; boot passes `enforce_production_safety`; full register→verify-email→ask journey green (see §4) |

## 3. Minor findings & hygiene fixes

| Finding | Status |
|---|---|
| Orphan Windows `uvicorn` process (PID 33108, old 0.6.2 code) shadowed port 8000 ahead of Docker — this, not the app, served the stale-version health probe | Killed; container owns :8000 and reports `openapi.json info.version = 0.9.1` |
| Local `.venv` editable metadata drifted (reported 0.1.0; source is 0.9.1) | `pip install -e .` refreshed → 0.9.1 |
| 8 stray empty root dirs (`docsadr`, `docsai`, `docsapi`, `docsarchitecture`, `docsdata`, `docsoperations`, `docssecurity`, `docstesting`) — artifact of a bad copy | Deleted |
| Windows reserved-name junk file `nul` | Deleted |
| Tracked 1.4 MB `apps/api/dev.db.bak-wave2` + ad-hoc root script `_g3_local.py` | Untracked via `git rm` (local index only, no commit); script moved to `apps/api/scripts/gate_g3_local.py` |
| Deploy record was stale (`dfa9fe4`/v0.9.0, dead tunnel URL) | Updated in `docs/VERCEL_DEPLOY_RECORD_2026-09-13.md` |
| Live production secrets existed only in container env | Persisted to gitignored `.env.production.local`; `.gitignore` extended for `.mailpit/` (SMTP TLS cert dir) and that file |
| Port 5173 served a different project ("AgroBridge") — not this repo | No action; dev port for this app is free |

## 4. Verification evidence (what was run)

### Code quality gates (API)
- `ruff check src tests scripts` → **All checks passed**
- `ruff format --check` (conftest edit) → clean
- `mypy src` (108 files) → **Success: no issues found**
- `pytest tests` → **628 passed, 6 skipped, 0 failed** (two independent full runs: 775s, 727s)
- `pip-audit` → **No known vulnerabilities**
- Alembic migration tests (`test_school_model`, `test_evaluation_alembic`) → green after conftest fix

### Code quality gates (Web)
- `tsc --noEmit` → clean
- `vitest run` → **43 files / 126 tests passed**
- `npm run build` → production bundle builds (index 288.56 kB / 96.02 kB gzip)
- `prettier --check src` → clean
- `npm audit --omit=dev` → **0 vulnerabilities**

### Live site as a user (https://bangla-gpt-app.vercel.app, in-browser GUI + API probes)
| Journey | Result |
|---|---|
| Student login `student@demo.com` → home renders, auto-session persists | ✅ |
| AI tutor: subject chip গণিত → ask "মৌলিক ও যৌগিক সংখ্যা কী?" → **SSE streams tokens**, structured answer (সহজ ব্যাখ্যা / উদাহরণ / মূল বিষয়), 98% confidence, "পাঠ্যবই-সমর্থিত", 3 evidence chips, feedback/reteach/save-note buttons | ✅ |
| Out-of-curriculum question → honest refusal with reason (`insufficient_evidence`) and low-confidence warning | ✅ |
| Quiz: 3-question math run → per-question review, score 33%, chapter tags, "বুঝিয়ে দিন" → hands off into tutor with the question | ✅ |
| Learn page: class picker (শ্রেণি 1–12) + subject cards for class 6 (science/mathematics/bangla) | ✅ |
| Me page: profile, streak, daily-activity heatmap (real dates, per-day counters) | ✅ |
| Teacher login `teacher@demo.com` → dashboard with students/classes/draft-papers counters, sidebar nav | ✅ |
| Parent login `parent@demo.com` → `/parents/me/children` 200 `[]`, dashboard reachable | ✅ |
| Language toggle (bn ↔ en) flips `html lang` and all UI copy | ✅ |
| Conversation history sidebar lists past chats (create/persist/rename/delete affordances present) | ✅ |
| Fresh registration (production mode): register → verification email delivered via SMTP → `/auth/verify-email` issues token → grounded tutor answer | ✅ |
| Legacy demo accounts still log in after JWT rotation (password hashes intact; old tokens invalidated — correct) | ✅ |
| `/api/health` 200, `/api/openapi.json` **version 0.9.1**, 116 paths | ✅ |
| `/metrics` behind the Vercel proxy → 403 `metrics access denied` (production gate active) | ✅ |

### Version/deployment sync
- Vercel production bundle: rebuilt and redeployed from current source (`bangla-gpt-k3uhbryku…` promoted to `bangla-gpt-app.vercel.app`).
- `api-live`: image `bangla-gpt-api:v0.9.1` built from working tree (verified `normalize_query` present, file-DB default present).
- Live `openapi.json` reports **0.9.1** through both :8000, the tunnel, and the Vercel `/api` proxy.
- Container stack: `api-live` (healthy) · `api-mailpit` (healthy) · `api-tunnel` · `web-preview:v0.9.1` (:8081, healthy).

## 5. Architecture / SOP assessment (enterprise conformance)

| Area | Grade | Notes |
|---|---|---|
| Repo layout | A | `apps/api` + `apps/web` monorepo; Dockerfile, compose profiles, deploy/ (caddy, prometheus, grafana, pgbackrest), docs/ with ADRs, runbook, OWASP checklist, eval datasets |
| API structure | A | Thin 332-line `main.py`; 16 routers, 28 services; production boot-guard (`enforce_production_safety`) — now actually exercised by the live container |
| Web structure | A | 11 page groups, lazy routes, React Query, SSE client with fallback, PWA + Capacitor, i18n, DOMPurify markdown lane |
| Data layer | A | 20+ Alembic revisions, tested upgrade/downgrade, PII at-rest encryption wired with a real key |
| Security | A | PBKDF2 200k, JWT rotation hygiene, rate limiting, CSP + security headers, metrics gating verified 403, no secrets tracked (`repository-sanity` rules pass; `.env.*` ignored) |
| Testing | A | 628 pytest + 126 vitest, hermetic conftest, eval gate files present (eval-gate workflow not executed per policy) |
| Docs/governance | A− | Scorecard claims "100/100" while P0 live-site outage existed — this audit replaces its conclusions for deployment/ops; scorecard should be regenerated post-fix |
| Operational risk (accepted, documented) | C | Vercel API origin is a **quick tunnel** (rotates on restart) to the owner's machine. Documented in the deploy record. Enterprise remedy = named Cloudflare tunnel or a VM/PaaS API origin; requires owner credentials/decision — out of scope for this pass |

## 6. Remaining recommendations (non-blocking)

1. **Stabilize the API origin** — replace the quick tunnel with a named tunnel or VM so `vercel.json` never needs redeploying on restart. (Documented caveat #1/#2 already in the deploy record.)
2. **Wire a real LLM provider** — live API runs `LLM_PROVIDER=mock` (grounded canned answers). Set provider + key to enable real AI; the routing/eval lane is already in place.
3. **PostgreSQL for prod data** — SQLite at `/data/app.db` survives container restarts via volume, but compose already ships a Postgres profile; moving the live stack to it matches the documented target architecture.
4. **Rotate demo passwords before public launch** — `Demo@1234` accounts are seeded for QA on the shared live DB.
5. **Regenerate `FINAL_ENTERPRISE_100_SCORECARD.md`** against post-audit state (its revision note is now stale).

## 7. Final state

- Repository: hygiene-clean, all quality gates green, no commits/pushes made.
- Running stack: **identical to the final v0.9.1 source**, production-safe boot config.
- Live URL: https://bangla-gpt-app.vercel.app — every tested user journey and parameter functions; frontend, proxy, streaming, and all role dashboards verified in-browser.
