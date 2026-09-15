# FULL QA / ENTERPRISE AUDIT — 2026-09-15

> **Scope:** app, codebase, repository structure, live deployment sync, user-journey testing,
> and (phase 2) the full CI/CD pipeline run under release **v0.9.2**.
> **Policy (phase 1):** no git commits, pushes or CI were executed. Container redeploy + Vercel
> redeploy were performed because "live must sync with final" was an explicit goal.
> **Phase 2 (same day):** the directive was lifted — see §8 for the full pipeline execution.

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

---

## 8. Phase 2 — full CI/CD pipeline execution (v0.9.2, same day)

Directive lifted: the audited condition was shipped through the real pipeline under strict SOP.

### 8.1 Release commits (conventional, logical units — 9 total on `main`)

```
c289433 fix(api): production-boot guard + Bangla input-boundary NFKC + hermetic tests
320ed1f chore(repo): move G3 seed script into scripts/, drop tracked DB backup blob
52281b0 chore(gitignore): exclude local mailpit TLS dir and production env file
0a4bec2 fix(web): repoint /api proxy at live tunnel URL (live site was 502)
29f70eb chore(release): v0.9.2 — live-hardening patch release
052454a docs: enterprise QA audit evidence (2026-09-15) + ADR/architecture/ops records
791fb88 ci: hermetic import-time settings patch + step-isolated migration DBs
7d04b14 chore(web): repoint /api proxy to current tunnel host (quick-tunnel rotation)
45aea3c docs: record final v0.9.2 live sync (tunnel host amd-reproduction-clips-cricket)
```

Pre-push secret scan of the full diff: no real secrets in any commit (`.env.production.local`,
`.mailpit/` certs, live env dump all gitignored; only placeholders appear in tracked docs).

### 8.2 First pipeline pass — CI caught a real latent defect (P1)

**Run 34894963825 (API CI) failed** on both Python 3.11/3.12 at "Alembic migration check":
`sqlite3.OperationalError: table users already exists`.

Root cause (proven locally): `main.py:320` builds a module-level `app = create_app()` for
gunicorn; test collection imports it **before** any fixture runs. With the new file-DB default
and no `.env` on CI, that import created `./bangla_gpt.db` with the full schema during the
pytest step, and the following alembic step then collided with it. The old in-memory default
had masked this for the suite's whole life — CI was the first honest environment to expose it.

**Fix (commit 791fb88):**
- `tests/conftest.py` applies the hermetic `Settings` patch at **module (import) time**, not only
  via the autouse fixture — collection-time `create_app()` now always gets an in-memory DB.
- CI hardening: the alembic check and smoke steps pin `DATABASE_URL` to throwaway files
  (step isolation), and the Postgres job now pins `DATABASE_URL` so its "migration cycle against
  Postgres" genuinely runs against the service instead of silently falling back to SQLite.

### 8.3 Final pipeline results (all green)

| Workflow | Trigger | Run | Result |
|---|---|---|---|
| API CI | push `791fb88` | 34929608797 | **success** — lint (3.11+3.12), format, mypy, 628 tests, pip-audit, **alembic up/down/up cycle**, smoke (116 paths), Postgres engine job, golden retrieval benchmark, Docker build, **Trivy HIGH/CRITICAL gate (0 fixable)**, container health + `/ready` provider probe, web job (vitest 126 + npm audit + build) |
| Repository Sanity | every push | all | success — no tracked `.env`, foundation files, workflow YAML valid |
| Eval gate | push | all | success — golden-set regression ≤2pp (measured locally first: grounded 1.0000 vs baseline 0.9984) |
| Release & Deploy | tag **v0.9.2** | 34894969518 | success — GHCR images `api:v0.9.2` + `web:v0.9.2` built and pushed; SSH deploy job skipped by design (`DEPLOY_ENABLED` not set — host secret belongs to owner) |
| API CI re-run | push `7d04b14`, `45aea3c` | 2 more | success (docs/proxy repoints are config-only) |

### 8.4 Post-pipeline live sync + user re-test

- `api-live` rolled to **v0.9.2** (same production boot config; data volume `api-live-data`
  preserved; alembic schema unchanged). Docker Desktop had restarted mid-session; the api/web
  tunnels were recreated (quick-tunnel hostnames rotate — documented caveat, now re-confirmed).
- `vercel.json` → `https://amd-reproduction-clips-cricket.trycloudflare.com`; Vercel production
  redeployed. `web-preview` rebuilt to v0.9.2 (:8081) for full-stack parity.
- **Live evidence:** `https://bangla-gpt-app.vercel.app/api/openapi.json` → **version 0.9.2**;
  `/api/health` 200; GHCR pull requires `read:packages` (owner PAT) — container was rebuilt
  from the same CI-validated commit instead (runtime code of `791fb88`/`7d04b14` vs tag `v0.9.2`
  is identical: test/CI/config only, verified via `git diff v0.9.2..HEAD -- apps/api/src apps/web/src` = empty).
- **User re-test on v0.9.2 (browser):** student login ✅, tutor ask → 98% confidence,
  "Textbook-backed" badge, 3 evidence excerpt chips ✅, quiz (3q run → result → explain) ✅,
  bn/en UI (both verified) ✅.

### 8.5 Verdict (phase 2)

**PASS — current condition live in production: app = codebase = repo = tag `v0.9.2`,
all four pipelines green, every user-facing parameter functionally verified on the live URL.**

### 8.6 Follow-up verification: "is the Vercel link actually on the final version?" (same day)

Direct evidence gathered when re-asked:

| Check | Result |
|---|---|
| Production bundle at `bangla-gpt-app.vercel.app` | `index-ncjoE9UB.js` + `index-C316nnxs.css` — **byte-identical hashes** to the local `apps/web/dist` built from v0.9.2 source |
| `/api/openapi.json` through the live proxy | **version 0.9.2** |
| Commits after the last successful deploy (`45aea3c`, `f4cc47f`) | docs-only; `git diff` shows zero `apps/web/src` / `apps/api/src` runtime changes → live bundle remains the correct final artifact |

**Finding fixed during this check:** the project's GitHub integration had auto-triggered
production deploys for every push — and they were **all failing** (`vite: command not found`),
because the Vercel project's Root Directory was unset (repo root instead of `apps/web`). The
`bangla-gpt-app.vercel.app` alias therefore remained pinned to the last manual `vercel --prod`
deploy. Corrected via the Vercel API: `rootDirectory=apps/web`, `installCommand=npm ci`,
`buildCommand=npm run build`, `outputDirectory=dist`. The push of this commit is the
verification that git-push auto-deploy now reaches **Ready** and promotes the alias — closing
the CD gap so future pushes deploy automatically (SOP: CI must be the ship path, not the CLI).
