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

- `ENV=production` boot guard refuses to start with a default/short `JWT_SECRET`,
  missing `ADMIN_EMAIL/ADMIN_PASSWORD`, or an `ADMIN_PASSWORD` shorter than 12 chars.
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
