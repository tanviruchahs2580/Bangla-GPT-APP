# GAP ANALYSIS — Fully Usable & Deployable Product

**Date:** 2026-08-25 · Repo head at analysis: `0ad6833` (CI green) · Tag: `v0.1.0-rc1`
Every "missing" item below was **verified against actual code** (not assumed).
Legend: 🔴 blocks real users · 🟠 blocks public production deploy · 🟡 required before scale/pilot

---

## A. CURRENT CONDITION (what exists, verified)

| Layer | State |
|---|---|
| API | FastAPI; 21 endpoints; JWT auth (PBKDF2 200k + HS256); 4-role RBAC w/ object-level checks; quiz+progress; teacher/parent/admin dashboards; GDPR delete (`DELETE /users/me`); Prometheus `/metrics`; JSON logs + X-Request-ID; rate-limit (login/tutor, per-process) + body-cap; coverage-based grounding gate |
| AI | `LLMProvider` factory — **only `mock` implemented**; unknown provider → loud 503 on `/ready` |
| NCTB | Official curriculum corpus pipeline live: 9 acquired artifacts (sha256 manifest committed), Bijoy→Unicode conversion, QC report, chapter-parented chunks, `NCTB_CORPUS_DIR` wiring, eval harness (refusal 4/4) |
| DB | SQLite (in-mem tests / file prod-ready path), Alembic 2 revisions, upgrade→downgrade→upgrade verified |
| Web | React 18 + Vite TS dashboard (all roles), type-checked build, dev proxy `/api` |
| Ops | Dockerfile (non-root, healthcheck), CI = ruff/format/mypy/pytest(3.11+3.12)/pip-audit/alembic/smoke + web build + docker smoke, runbook, API docs, MIT, 96 tests green from clean clone |

**Bottom line:** code-quality-wise this is a release candidate. What separates it from a *usable public product* is one missing integration (real LLM), several deployment components, and child-safety/legal items.

---

## B. MISSING STEPS → SOLUTIONS (complete register)

### 🔴 B1. Real LLM provider not implemented
- **Verified:** `providers/__init__.py` supports only `mock`; `.env.example` advertises `GEMINI_API_KEY` but no code reads it.
- **Impact:** every `/tutor/ask` answer is `[mock]` text — app is not usable as a tutor yet.
- **Solution:** add `providers/gemini.py` implementing `LLMProvider` via Gemini REST (`generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=…`). New settings: `gemini_api_key`, `gemini_model` (default `gemini-2.0-flash`), `llm_timeout_seconds`, `llm_max_retries`. Factory maps `LLM_PROVIDER=gemini`. Tests with stubbed HTTP (no key in tests). Acceptance: eval harness runs against real model; hallucination-rate measured on `eval/sample_questions.json`.

### 🔴 B2. Prompt-injection hardening before real LLM
- **Solution:** wrap evidence as data (`<evidence>…</evidence>` delimiters + explicit instruction-ignoring rule in SYSTEM_PROMPT), strip/flag control phrases from retrieved chunks, cap context chars. Test: poisoned-chunk fixture must not change refusal behavior.

### 🔴 B3. Password reset / email verification absent
- **Verified:** no email code anywhere; forgotten password = permanently locked account.
- **Impact:** real users WILL be locked out; unusable for schools.
- **Solution:** `smtp_host/port/user/from` settings + `password_resets` table + `POST /auth/forgot` / `POST /auth/reset` (single-use, 30-min token). Dev mode logs token instead of sending. Optional: student registration via parent/teacher invitation codes for minors.

### 🔴 B4. Child privacy & consent documents/flow (students are minors)
- **Solution:** Bangla+English Privacy Policy & ToS pages (data collected: name/email/class/quiz answers; retention; parent rights); parental-consent checkbox + guardian email at student signup; data-export endpoint (JSON download of own data alongside existing delete). Legal review per Bangladesh context.

### 🟠 B5. No CORS configuration
- **Verified:** zero CORS references in API.
- **Impact:** web dashboard served from any other domain/port than the API cannot call it in production.
- **Solution:** `CORSMiddleware(allow_origins=settings.allowed_origins, allow_credentials=False)`; new setting `allowed_origins: list[str] = []`. Never use wildcard with credentials.

### 🟠 B6. JWT secret has insecure default and NO production guard
- **Verified:** `config.py:14 jwt_secret="dev-insecure-change-me"`; nothing validates at startup.
- **Solution:** startup check in `create_app`: if `ENV=production|staging` and (`jwt_secret` == default or len < 32 or `admin_password` unset) → raise at boot. Same guard for `ENV=production` + SQLite default URL (force explicit choice).

### 🟠 B7. Single-process server; no worker config
- **Verified:** Dockerfile CMD = bare uvicorn (1 process); rate limiter in-memory.
- **Solution:** CMD `gunicorn -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-2} -t 60 bangla_gpt_api.main:app`; add `gunicorn` dep. Pair with B8.

### 🟠 B8. Rate limiter per-process (bypassed under >1 worker)
- **Solution:** `RateLimitBackend` protocol; `MemoryBackend` (current) + `RedisBackend` (sliding window INCR/EXPIRE); setting `rate_limit_backend=memory|redis`, `redis_url`. Default stays memory (zero-dep pilot); Redis for multi-worker.

### 🟠 B9. Postgres path untested (needed for HA/scale)
- **Solution:** add `psycopg[binary]>=3` dependency; CI job with `postgres:16` service running alembic upgrade/downgrade + full pytest against PG; fix any SQLite-only SQL. Keep SQLite for single-node pilots.

### 🟠 B10. No deployment topology file (compose) and no TLS termination
- **Solution:** `docker-compose.yml` profiles:
  - `core`: api (+ volume `pgdata` when POSTGRES used, or sqlite volume), caddy (auto-HTTPS via Caddyfile: `api.example.com { reverse_proxy api:8000 }`), web (nginx serving dist + `VITE_API_BASE=https://api.example.com` baked at build)
  - `ai`: redis (when B8 enabled)
  - `obs`: prometheus + grafana + node-exporter (scrape `/metrics`)
  Parameters documented per env var; `.env.production.example` added.

### 🟠 B11. No CD: image never pushed/deployed
- **Solution:** workflow `release.yml`: on tag `v*` → docker build multi-arch → push `ghcr.io/<owner>/bangla-gpt-api:<tag>` (+ web image) → optional SSH deploy step (`docker compose pull && up -d`) gated by environment secret `DEPLOY_SSH_KEY`. Rollback = redeploy previous tag.

### 🟠 B12. Backups manual only
- **Solution:** compose sidecar `backup` (cron): SQLite → `sqlite3 .backup` nightly or `pg_dump`; rotate 14 daily + 8 weekly; rsync/rclone offsite; monthly automated restore test script (`restore_test.sh`) asserting row counts.

### 🟠 B13. Monitoring/alerts unwired
- **Solution:** Prometheus scrape config + Grafana dashboard JSON (requests/sec, 5xx ratio, p95 latency, readiness status, process RSS); Alertmanager rules: 5xx>2% 5m, p95>1s 10m, `/ready` down 2m, disk>80%. Sentry DSN optional (`sentry_sdk` init behind env).

### 🟡 B14. `.env.example` incomplete vs Settings
- **Verified:** missing `NCTB_CORPUS_DIR` (and upcoming B1/B5/B8 vars).
- **Solution:** regenerate template listing EVERY setting with safe defaults + production notes (single source: pydantic Settings fields).

### 🟡 B15. LOG_LEVEL hardcoded INFO
- **Verified:** `logging_config.py` sets level literally.
- **Solution:** `Settings.log_level: str = "INFO"`; configure via `getattr(logging, level.upper())`; validate value.

### 🟡 B16. Load test never executed
- **Solution:** k6 script (mixed workload: 70% ask-auth, 20% progress, 10% login) targeting 500/1000 concurrent; run against staging compose stack; record p50/p95/error-rate; tune workers/limits from results. Gate: error<1%, p95<800ms at target.

### 🟡 B17. Admin lifecycle
- **Solution:** force password change flag on bootstrap admin first login; document rotation in runbook; optionally TOTP 2FA for admin role.

### 🟡 B18. Textbook corpus (পাঠ্যপুস্তক) still curriculum-docs only
- **Solution options:** request official e-book channel/NCTB permission; or OCR pipeline (Tesseract ben + layout stage) once PDFs obtained; wire through same ingestion (adapter already isolated).

### 🟡 B19. Golden dataset + dense/hybrid retrieval benchmark
- Per master §48–§51: build 100×9-case golden set from verified content; then embedding benchmark infra; only then add hybrid+reranker. Blocked today by E3 infra, not by decision.

### Explicitly deferred (documented non-gaps): mobile app, offline sync, voice I/O, conversation memory, payment/billing — roadmap items, not blockers for v1 usable/deployable web product.

---

## C. ORDERED EXECUTION PLAN

| Phase | Items | Exit criteria |
|---|---|---|
| 1. Usable tutor | B1, B2, B14 | real answers w/ citations; eval measured |
| 2. Safe accounts | B3, B4, B17 | reset flow tested; policies published |
| 3. Deployable core | B5–B7, B10–B12, B14–B15 | staging URL HTTPS-green, backups restoring, alerts firing |
| 4. Scale-ready | B8, B9, B13, B16, B18, B19 | k6 targets met on PG+Redis; textbook corpus ingested |
| 5. Ship | B11 CD to prod | prod tag deployed, monitored, backed up |

**Parameter checklist (nothing omitted):** ENV, LLM_PROVIDER, GEMINI_API_KEY, GEMINI_MODEL, LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES, DATABASE_URL, NCTB_CORPUS_DIR, JWT_SECRET(≥32), JWT_EXPIRE_MINUTES, ALLOWED_ORIGINS, RATE_LIMIT_LOGIN_PER_MINUTE, RATE_LIMIT_TUTOR_PER_MINUTE, RATE_LIMIT_BACKEND, REDIS_URL, MAX_BODY_BYTES, ADMIN_EMAIL, ADMIN_PASSWORD, WEB_CONCURRENCY, LOG_LEVEL, SMTP_*(host/port/user/pass/from), SENTRY_DSN(opt), VITE_API_BASE(web build).
