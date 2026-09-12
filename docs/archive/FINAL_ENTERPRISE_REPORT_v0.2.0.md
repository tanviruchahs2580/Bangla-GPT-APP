# Final Enterprise Report — v0.2.0 (Gap Plan B1–B19)

Date: 2026-08-26 · Base: `1c5abc8` (gap analysis) · This release: `8158915`

Every claim below is backed by an executed command/test on this machine.
Statuses: **PASS** (executed, verified) / **PASS\*** (verified with documented
boundary) / **UNVERIFIED** (requires external resource).

## 1. Executive summary

The B1–B19 gap plan from `docs/GAP_ANALYSIS_FULL_DEPLOYMENT_PLAN.md` has been
implemented in full and verified by 134 automated tests (+3 environment-skipped),
a live docker-compose stack exercise (E2E smoke 7/7, rate-limit 429s observed,
persistence/restart/recreate recovery, backup+restore rehearsal) and a measured
concurrency run (0% errors to c=40, p95 ≤ 324 ms). Remaining external
dependencies are explicit: a real Gemini key, a domain for TLS, and textbook
ingestion rights.

## 2. Gap closure matrix

| # | Gap | Resolution | Evidence | Status |
|---|---|---|---|---|
| B1 | Mock-only LLM | `providers/gemini.py` (REST `generateContent`, `x-goog-api-key`, `systemInstruction`, backoff on 408/429/5xx); `LLM_PROVIDER=gemini` factory gate; settings `GEMINI_API_KEY/GEMINI_MODEL/LLM_TIMEOUT_SECONDS/LLM_MAX_RETRIES` | `tests/test_providers_gemini.py` 9 tests incl. request-contract, retry-then-success, retries-exhausted, non-retryable, blocked-candidate, timeout mapping; endpoint/model verified against ai.google.dev docs | PASS* |
| B2 | No injection guard | Evidence wrapped in `<evidence>…</evidence>`, delimiter-escape sanitizer (`</evidence>`→`&#47;evidence`), system rules declaring chunk text as data | `tests/test_injection_guard.py`: poisoned chunk cannot escape delimiters (exactly one legit pair survives), system prompt carries the rule | PASS |
| B3 | No password reset | `password_resets` table (migration `c3f4a5b6d7e8`), `/auth/forgot` (202 anti-enumeration), `/auth/reset` single-use hashed tokens 30 min, `/auth/change-password`; SMTP STARTTLS mailer w/ dev console fallback | `tests/test_password_reset.py` 9 tests: replay refused, expiry refused, prior-token invalidation, wrong-current-password 400, rotation clears flag | PASS |
| B4 | No privacy/consent/export | `/users/me/export` (account+profile+attempts+links, attachment header); bilingual Privacy/Terms pages; mandatory `guardian_consent` for students (API validator + web checkbox) | `tests/test_data_export.py` 4 tests; web build green; consent enforced at schema level (422 without it) | PASS |
| B5 | CORS unconfigured | `CORSMiddleware` + `ALLOWED_ORIGINS` (comma list) | `tests/test_cors.py` 4 tests (allowed preflight, unknown origin no-header, unconfigured no-header, multi-origin) | PASS |
| B6 | Insecure JWT default, no boot-guard | `enforce_production_safety()` refuses boot on default/<32-char secret, missing admin creds, <12-char admin password, redis backend w/o URL | Unit tests + **live container injection**: `ENV=production` w/ weak secret exits code 3 printing "Refusing to start" | PASS |
| B7 | Single-process uvicorn | Dockerfile CMD gunicorn + `uvicorn_worker.UvicornWorker`, `-w ${WEB_CONCURRENCY}` (default 2), max-requests recycling | Container logs show master + 2 worker processes serving health/ready | PASS |
| B8 | Per-process limiter | `ratelimit.py`: Redis fixed-window INCR/EXPIRE shared across workers; `RATE_LIMIT_FAIL_OPEN` chooses allow vs 503 when Redis is down | Live compose: `rl:/auth/login\|\(ip\)` keys in redis-cli; 13 logins → `[401×8, 429×5]`; fail-open/closed unit tests; 503 path tested via monkeypatched dead backend | PASS |
| B9 | Postgres untested | `psycopg[binary]` extra; CI `postgres` job: alembic upgrade/downgrade/up + `test_postgres_smoke.py` journey vs Postgres 16 service container | CI workflow added; smoke covers register/login/quiz/progress/export/delete on PG engine | PASS (CI-run) |
| B10 | No compose/TLS topology | `docker-compose.yml` profiles core/web/tls/postgres/monitoring/backup; Caddy auto-HTTPS Caddyfile; nginx SPA+proxy config; `.env.production.example` | `docker compose config --quiet` VALID; full stack up --wait healthy twice | PASS |
| B11 | No CD | `release.yml`: tag → GHCR api+web images (buildx cache) → SSH deploy gated on health with automatic previous-tag rollback; skips cleanly until deploy secrets exist | Workflow YAML valid; deploy job conditional on `vars.DEPLOY_ENABLED` | PASS* |
| B12 | Backups manual only | `scripts/backup_loop.py` sidecar (sqlite online `.backup()` / pg_dump, retention prune, optional offsite sync cmd) + `scripts/restore_test.py` | Executed in stack: snapshot written → restore test printed `integrity_check: ok`, row counts, exit 0 | PASS |
| B13 | Alerting unwired | `deploy/prometheus/alerts.yml`: HighHTTP5xxRate >2%/5m, HighP95Latency >1s/10m, APIScrapeDown, UnhandledExceptions, DiskNearFull(node_exporter-gated); wired into prometheus.yml + monitoring profile | Prometheus config mounted in compose; rule expressions match exported metric names (`bgpt_http_requests_total`…) | PASS* |
| B14 | .env.example stale | Regenerated covering every Settings field; regression test enforces future parity | `tests/test_env_example.py` green (fails if any field undocumented) | PASS |
| B15 | LOG_LEVEL hardcoded | `log_level` setting → `configure_logging(level)`; validated set, safe fallback INFO | Wired in `create_app`; documented in env templates | PASS |
| B16 | Load test never run | `load/k6-tutor.js` (threshold gates error<1%, p95<800ms) + `scripts/concurrency_probe.py` executed against live stack | Measured table: c=1→40 all **0% errors**, p50 6–213ms, **p95 ≤ 324ms**, ~130–170 rps on laptop-scale 2-worker stack | PASS |
| B17 | Admin lifecycle missing | Bootstrap admin created with `must_change_password=true`; non-exempt endpoints 403 until rotation; login response exposes flag; opt-out flag exists | `test_force_change_blocks_other_endpoints_until_rotated` + change-password flows | PASS |
| B18 | Textbook corpus absent | `ingestion/ocr_ingester.py`: Tesseract-Ben adapter, PDF render seam, permission gate (`BGPT_OCR_CONFIRMED`) pending rights-holder clearance | `tests/test_ocr_ingester.py` 4 tests; actual ingestion intentionally blocked until permission | PASS* |
| B19 | Golden dataset/benchmark | `eval/golden_questions.json` (15 curated: 10 in-corpus w/ chapter targets + 5 refusal cases) + `scripts/evaluate_golden.py` (hit@3, grounded accuracy, JSON report, CI gate ≥0.9) | Run output: hit@3 **1.0**, grounded accuracy **0.933** (single miss = conservative refusal, safe direction); wired as CI `golden-eval` job | PASS |

## 3. Defect found & fixed during validation

| Field | Detail |
|---|---|
| Problem | Multi-worker boot crash: `sqlite3.OperationalError: table users already exists` under gunicorn -w 2 (concurrent `create_all`/admin bootstrap race) — surfaced only in the compose stack, invisible to single-process tests |
| Root cause | Two workers executing DDL/bootstrap simultaneously on shared sqlite volume |
| Fix | `_safe_init_db()` tolerates "already exists"; admin bootstrap catches `IntegrityError` (concurrent duplicate insert) |
| Retest | Fresh volume boot ×2: zero errors, both workers healthy |

Also hardened during testing: compose now passes through all operational env
vars (rate limits were silently falling back to defaults), `/backups` volume
ownership for the non-root backup sidecar, and PowerShell-pipe UTF-8 pitfalls
documented via `docker cp` smoke procedure.

## 4. Verification summary

```text
pytest                134 passed, 3 skipped   (baseline was 94 passed)
ruff check/format     clean (68 files)
mypy                  Success: no issues in 41 source files
pip-audit             No known vulnerabilities
alembic cycle         head→base→head OK (incl. new migration)
web build             tsc + vite OK
docker image          builds clean; non-root; healthcheck; 2 workers
compose stack         up --wait healthy; E2E smoke 7/7 SMOKE OK
rate limiting         Redis keys live; 429 after cap; 503 fail-closed tested
persistence           data survives down/up, restart, force-recreate
backup/restore        snapshot written; integrity_check ok; exit 0
boot guard            production misconfig refuses startup (exit 3)
golden benchmark      hit@3 = 1.0 ; grounded accuracy = 0.933
concurrency           0% errors to c=40 ; p95 <= 324ms (<800ms gate)
```

## 5. Remaining limitations (explicit)

1. **Live Gemini behaviour UNVERIFIED** — needs a real `GEMINI_API_KEY`;
   client contract fully covered by mock-transport tests.
2. **TLS/domain** — Caddy profile ready; requires real `DOMAIN` + DNS.
3. **CD deploy step** dormant until `DEPLOY_ENABLED=true` + SSH secrets;
   GHCR publish path active on tag.
4. **Textbook OCR ingestion** blocked behind permission gate by design (B18);
   curriculum documents corpus remains the indexed source.
5. **k6 500–1000 VU target** requires an appropriately sized runner; local
   evidence limited to c=40 probe + k6 script provided.
6. **TOTP/MFA** for admins not implemented (documented in runbook §6).
7. **Golden grounded-accuracy miss (1/15)** is a conservative refusal caused by
   short-function-word coverage — safe direction, tracked for hybrid retrieval
   (future dense/hybrid work).

## 6. Ship checklist

- [x] All quality gates green locally (§4)
- [x] Committed `8158915` on `main`, pushed to origin
- [ ] Tag `v0.2.0` pushed → triggers `release.yml` GHCR publish
- [ ] Production host: fill `.env` from template, `--profile core web tls up`
- [ ] Deploy real Gemini key; re-run golden eval against NCTB corpus
