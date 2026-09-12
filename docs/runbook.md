# Operations Runbook — Bangla GPT APP

Audience: engineer/SRE deploying or operating the platform.
Every command below has been executed and verified on this codebase.

## 1. Start locally (dev)

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
# optional persistent DB:
#   set DATABASE_URL=sqlite:///./bangla_gpt.db
#   .venv\Scripts\alembic upgrade head
.venv\Scripts\python -m uvicorn bangla_gpt_api.main:app --reload
# verify:
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

> SEC-002 note: local/dev boots use the insecure `dev-insecure-change-me`
> JWT default on purpose and log an `InsecureKeyLengthWarning` — that noise
> is expected locally and never reaches staging/production (the boot guard
> refuses short/default secrets there). For the quiet, CI-equivalent local
> path, run servers and one-off checks with `ENV=ci` plus a 32+ byte
> `JWT_SECRET`; the pytest suite already uses 39-char test secrets, so its
> warnings come only from the shortest-lived dev-default cases.

Web dashboard (dev): `cd apps/web && npm install && npm run dev` → http://localhost:5173
(dev server proxies `/api/*` to `http://127.0.0.1:8000`). Production build: `npm run build`.

## 2. Staging / production deployment (docker compose)

Full topology lives in `docker-compose.yml` with profiles:

```bash
cp .env.production.example .env    # fill every required value first!
docker compose --profile core up -d --wait          # api + redis (shared Redis limiter)
docker compose --profile core --profile web --profile tls up -d --wait   # + nginx dashboard + Caddy auto-HTTPS
docker compose --profile monitoring up -d           # Prometheus (+ Grafana)
```

- `ENV=production` (and `ENV=staging` — S5.1 parity: staging runs the same
  strict guard) boot guard refuses to start with a default/short `JWT_SECRET`,
  missing `ADMIN_EMAIL/ADMIN_PASSWORD`, or an `ADMIN_PASSWORD` shorter than 12 chars.
- Env-surface drift is mechanically guarded: `pytest apps/api/tests/test_env_parity.py`
  fails if `.env*.example` documents a variable with no `Settings` field (or vice
  versa outside the explicit INFRA_ONLY compose/build list), or if
  `docker-compose.yml` interpolates a variable that is neither documented in
  `.env.production.example` nor defaulted inline. New deploy vars MUST be added
  to one of those two places.
- Set `API_HOST_PORT=18000` in `.env` ONLY for staging/debug when you need direct
  host access to the API; production traffic must enter through Caddy/nginx.
- Postgres profile: start `--profile postgres`, point `DATABASE_URL` at
  `postgresql+psycopg://…` and run alembic (§3).

Single-container run remains available:

```bash
docker build -t bangla-gpt-api:local .
docker run -d --name bgpt -p 8080:8000 \
  -e ENV=production -e DATABASE_URL=sqlite:////data/bangla_gpt.db \
  -e JWT_SECRET="$(openssl rand -hex 32)" \
  -e ADMIN_EMAIL=admin@example.com -e ADMIN_PASSWORD='…' \
  bangla-gpt-api:local
curl -fsS http://127.0.0.1:8080/health && curl -fsS http://127.0.0.1:8080/ready
```

Image is python:3.12-slim, runs as non-root `appuser`, HEALTHCHECK on `/health`,
and serves gunicorn+uvicorn workers (`WEB_CONCURRENCY`, default 2).

End-to-end stack smoke (executed inside the api container):

```bash
docker cp scripts/smoke_stack.py <api-container>:/tmp/smoke_stack.py
docker compose exec -T api python /tmp/smoke_stack.py   # expect SMOKE OK
```

### Scheduled background jobs (S5.4): inline vs ARQ

Two jobs run on a schedule: the **weekly parent digest** (ISO Sunday ≥16:00 UTC)
and the **nightly weakness rollup** (daily ≥21:00 UTC). `JOBS_BACKEND` chooses
the scheduler:

- `JOBS_BACKEND=inline` (default): each web process runs the loop itself.
  Fine for single-process dev; on a restart the period is not re-fired.
- `JOBS_BACKEND=arq`: web processes silence their loops; run ONE worker:

```bash
docker compose --profile worker up -d    # command: arq worker.WorkerSettings
# bare metal equivalent:
REDIS_URL=redis://redis:6379/0 JOBS_BACKEND=arq arq worker.WorkerSettings
```

Idempotency does NOT depend on running exactly one scheduler: every period is
claimed by a composite-PK insert into the `job_runs` table, so a misconfigured
mix of inline workers plus an ARQ cron still sends each weekly digest (and
runs each nightly rollup) **at most once**; losers skip with `already_ran`.
The digest needs working SMTP (`SMTP_ENABLED` + relay, §2 production list);
without SMTP it logs `skipped=smtp_not_configured` instead of failing.


## 3. Database migrations

Alembic is authoritative for any file/persistent DB (`create_all` only serves
in-memory test DBs; multi-worker boots tolerate concurrent create races).

```bash
cd apps/api
DATABASE_URL=<url> alembic upgrade head      # apply
DATABASE_URL=<url> alembic downgrade base    # rollback all
DATABASE_URL=<url> alembic current           # inspect
```

Verified cycle: `upgrade head → downgrade base → upgrade head` on SQLite (CI) and
Postgres 16 (CI service container).

### Expand–contract convention (S5.2 — required for zero-downtime deploys)

Rolling/blue-green deploys keep OLD and NEW app versions running simultaneously
against ONE database, so every migration must be safe for both at the same
time. Rules (all history in this repo already follows them; migrations are
append-only — never edit a revision that shipped):

1. **Expand** — add new columns as `NULL`/nullable (or with a server default);
   add new tables freely. Never rename a column: add the new name instead.
2. **Backfill** — a separate idempotent data migration (or background job) fills
   new columns in batches; deploys may interleave with it.
3. **Dual read/write** — release N+1 writes BOTH old and new columns and reads
   the old one; only after the whole fleet runs N+1 may code read only the new.
4. **Contract** — in a LATER release: drop the old column / enforce NOT NULL.
   A contract migration is only deployable when no live process uses the old
   shape; it never shares a release with the code that starts depending on it.
5. `downgrade` stays possible for one release (contract migrations downgrade by
   re-adding what they dropped; older than that, restore from backup instead).

**Rolling deploy procedure (health-gated, blue–green):**
`python scripts/deploy_rolling.py --old <host:port> --new <host:port>` starts
the new release alongside the old, polls `GET /ready` on it until ready
(boot guard + index built), flips the front proxy upstream atomically, then
drains the old instance (`SIGTERM` ≤ `--graceful-timeout 30s`). If `/ready`
never goes green the script flips nothing and exits 1 — the old release keeps
serving (verified locally with continuous load: 0 failed requests,
`scripts/deploy_rolling.py --demo`, see §10 note).

## 4. Backups & restore rehearsal (automated)

The `backup` compose sidecar runs `scripts/backup_loop.py` every
`BACKUP_INTERVAL_SECONDS` (default daily): online sqlite snapshot (or `pg_dump`
for Postgres) into the `backup_data` volume, prunes beyond `BACKUP_KEEP_DAYS`,
then executes `OFFSITE_SYNC_CMD` if configured.

```bash
docker compose --profile backup up -d                 # start scheduled backups
docker compose logs backup | tail                     # "sqlite backup written: …"
docker compose exec backup python /srv/scripts/restore_test.py --backup-dir /backups
# PASS: integrity_check ok + row counts printed
```

Manual backup (dev):

```powershell
Copy-Item bangla_gpt.db "backups\bangla_gpt_$(Get-Date -Format yyyyMMdd_HHmm).db"
```

Rehearsed 2026-08-26 in the compose stack: automated snapshot → restore test
(`integrity_check: ok`, row counts verified, exit 0).

## 5. Health checks, metrics & alerting

| Probe | Meaning | Action if failing |
|---|---|---|
| `GET /health` 200 | process up | restart container / check logs |
| `GET /live` 200 | request loop alive | orchestrator should restart |
| `GET /ready` 200 | DB reachable AND provider configured | 503 with provider message → fix `LLM_PROVIDER`; 503 `Database unavailable` → check DB path/volume |
| `GET /metrics` | Prometheus series | scraped by Prometheus (monitoring profile) |

Alert rules ship in `deploy/prometheus/alerts.yml`:

- `HighHTTP5xxRate` — >2% 5xx for 5 min (critical)
- `HighP95Latency` — p95 > 1s for 10 min (warning)
- `APIScrapeDown` — scrape target down 2 min (critical)
- `UnhandledExceptions` — any unhandled exception increase
- `DiskNearFull` — requires node_exporter (fires only when present)

Logs are JSON lines to stdout with `X-Request-ID` correlation. `LOG_LEVEL`
controls verbosity (DEBUG/INFO/WARNING/ERROR/CRITICAL).

## 6. Admin credential rotation

Bootstrap admin (`ADMIN_EMAIL`/`ADMIN_PASSWORD`) is created once; first login in
a fresh database returns `must_change_password=true` and blocks all other
endpoints until `POST /auth/change-password` succeeds.

Quarterly rotation procedure:

1. Log in as admin → `POST /auth/change-password` with current+new password
   (response issues a fresh JWT automatically).
2. If the password is lost: set a new `ADMIN_PASSWORD` env value only after
   deleting that user row from the DB (bootstrap re-creates it at next boot).
3. TOTP/MFA is NOT yet implemented — tracked as future hardening; until then,
   restrict `/admin/*` access at the reverse proxy or VPN layer.

## 7. Rollback

- **Release rollback:** redeploy previous tag — `git checkout vX.Y.Z &&
  docker compose pull && docker compose up -d`. The release workflow performs
  this automatically when its post-deploy health gate fails.
- **DB rollback:** `alembic downgrade <revision>` (verified cycle). Always take
  a backup (§4) before downgrading.
- **Bad release prevention:** CI gates (lint/format/type/tests/pip-audit/
  migrations incl. Postgres/golden-eval/container smoke) must pass before merge.

## 8. Known operational limits

- Redis rate limiting uses a fixed 60 s window; counts are approximate under
  heavy skew (standard trade-off vs sliding-window log).
- `RATE_LIMIT_FAIL_OPEN=false` (default) answers **503** on protected routes if
  Redis is down; set `true` to prefer availability over strictness.
- S5.3 caches (`/dashboard/summary` 60 s per user; RAG query results 5 min,
  SHA-256 hashed keys -- never the raw question) share the same
  `RATE_LIMIT_BACKEND=redis` switch: `redis` -> all pods share the caches,
  otherwise a bounded in-process cache. Redis failure never breaks a request;
  caches degrade to a miss. Expect up to 60 s of staleness on the home
  dashboard after a quiz is graded (spec'd cache window).
- SQLite is single-node; move to Postgres before horizontal scaling.
- Live Gemini behaviour needs a real `GEMINI_API_KEY`; contract tests cover the
  client, live latency/quota behaviour is UNVERIFIED until a key is deployed.
- Textbook (পাঠ্যপুস্তক) OCR ingestion is implemented behind a permission gate
  (`BGPT_OCR_CONFIRMED=yes`) pending rights-holder permission (B18).
- TOTP/MFA for admins not yet implemented (§6).

## 9. Pre-production checklist

- [x] Postgres CI job green (alembic + API journeys against Postgres 16)
- [x] Redis-backed shared rate limiting verified in compose stack
- [x] `JWT_SECRET` ≥32 random bytes enforced at boot in production
- [x] Automated backups scheduled AND restore rehearsed (§4)
- [x] Prometheus alert rules shipped (§5); Grafana provisionable via profile
- [x] Load/concurrency probe executed (scripts/concurrency_probe.py);
      k6 script provided in `load/k6-tutor.js` for larger-scale runs
- [ ] Real `GEMINI_API_KEY` deployed and live latency/quota validated
- [ ] Domain + ACME email set; Caddy TLS profile enabled; DNS pointed
- [ ] Offsite backup sync command configured (`OFFSITE_SYNC_CMD`)

## 10. v0.3 additions (chat, invites, retention)

### Secrets rotation (expanded)
- `JWT_SECRET`: rotate via `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
  Rotation invalidates all sessions (users simply log in again); do it in a
  maintenance window. Update the compose `.env` and restart `api`.
- Gemini key: replace in `.env` (`GEMINI_API_KEY`), restart api; verify with
  one live `/tutor/ask`. Old key must be revoked in AI Studio.
- SMTP credentials: rotate in `.env`; test via `/auth/forgot`.

### Capacity plan & load testing
- Baseline: 2 uvicorn workers handle ~120 concurrent quiz journeys at
  p95<300 ms (DB-bound). The LLM path is upstream-bound: budget ~2-8 s p95
  per ask at free-tier quota; scale by upgrading tier / adding keys, not
  workers.
- Run `k6 run -e BASE=... -e VUS=50 -e DURATION=5m load/tutor_load.js`
  before each release; thresholds inside fail on SLO breach.

### Data retention (D20)
- Conversations older than `CHAT_RETENTION_DAYS` (default 180) are purged by
  `POST /admin/maintenance/purge` (admin-only). Schedule it daily:
  `0 3 * * * curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" http://api:8000/admin/maintenance/purge`
  or trigger from the admin dashboard button weekly until automated.

### Email verification
- With `SMTP_ENABLED=true`, registration requires email verification before
  first login (`email_unverified` code drives UI copy + resend link).
- Without SMTP, accounts auto-verify (dev/small deployments only).

### Support ops & SLA (S5.10)
- Public status page: the web app serves `/status` from `GET /status`
  (presence/booleans only -- safe to link publicly; never exposes counts).
  Check the API directly with `curl http://api:8000/status`; a `degraded`
  payload names the failing component (database / cache / assistant).
- Feedback triage: admins work the queue at `GET /admin/feedback`
  (oldest open first). Target response times (support SLA):
  - **Sev-1** safety/regression reported via feedback (a `-1` rating whose
    comment hints at harm or outage): triage within **1 business day**.
  - **Sev-2** content/UX complaints: triage within **3 business days**.
  - Triage = mark `triaged` with an internal note; reopen any time -- the
    note is kept (evidence first).
- Support impersonation: mint via the admin dashboard ("support check"),
  always with a reason; the session is bounded to 15 minutes AND must be
  ended with the banner's exit button (revokes the token server-side).
  Both start and exit land in `GET /admin/audit?action=impersonation`.
  Admin-role targets are rejected server-side (support never gets powers).
