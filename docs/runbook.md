# Operations Runbook — Bangla GPT APP

Audience: engineer/SRE deploying or operating the API service.
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

## 2. Container deployment

```bash
docker build -t bangla-gpt-api:local .
docker run -d --name bgpt -p 8080:8000 \
  -e ENV=production \
  -e DATABASE_URL=sqlite:////data/bangla_gpt.db \
  -e JWT_SECRET="$(openssl rand -hex 32)" \
  -e ADMIN_EMAIL=admin@example.com -e ADMIN_PASSWORD='…' \
  bangla-gpt-api:local
curl -fsS http://127.0.0.1:8080/health && curl -fsS http://127.0.0.1:8080/ready
```

Image is python:3.12-slim, runs as non-root `appuser`, has a Docker HEALTHCHECK on `/health`.
Mount a volume for the SQLite file (e.g., `-v bgpt-data:/data`).

## 3. Database migrations

Alembic is authoritative for any file/persistent DB (`create_all` only serves in-memory test DBs).

```bash
cd apps/api
DATABASE_URL=sqlite:///./bangla_gpt.db alembic upgrade head      # apply
DATABASE_URL=sqlite:///./bangla_gpt.db alembic downgrade base    # rollback all
DATABASE_URL=sqlite:///./bangla_gpt.db alembic current           # inspect
```

Verified cycle: `upgrade head → downgrade base → upgrade head` (CI runs this every push).

## 4. Backup & restore (SQLite file DB)

```powershell
# Backup (RPO: schedule to taste, e.g. hourly copy + offsite sync)
Copy-Item bangla_gpt.db "backups\bangla_gpt_$(Get-Date -Format yyyyMMdd_HHmm).db"
# Restore
Stop service → Copy-Item backup.db bangla_gpt.db → Start service → alembic upgrade head
# Verify restore
sqlite3 bangla_gpt.db "SELECT count(*) FROM users;"
```

Rehearsed 2026-08-25: file copy → destroy → restore → row count verified (`RESTORE_OK`).
RPO/RTO are NOT yet formally defined — required before production pilot (see §8).

## 5. Health checks & monitoring

| Probe | Meaning | Action if failing |
|---|---|---|
| `GET /health` 200 | process up | restart container / check logs |
| `GET /live` 200 | request loop alive | container orchestrator should restart |
| `GET /ready` 200 | DB reachable AND provider configured | 503 with provider message → fix `LLM_PROVIDER`; 503 `Database unavailable` → check DB path/volume |
| `GET /metrics` | Prometheus series | scrape via Prometheus; alert on 5xx rate (`bgpt_http_requests_total{status="500"}`), p95 latency (`bgpt_http_request_duration_seconds`) |

Logs are JSON lines to stdout with `X-Request-ID` correlation — ship stdout to your log stack.
Alerting rules and dashboards are not yet provisioned (infra-pending).

## 6. Rollback

- **App rollback:** redeploy previous image tag; schema is forward-compatible within current revisions. Verify `/health` after rollout.
- **DB rollback:** `alembic downgrade <revision>` (verified `downgrade base → upgrade head`). Take a backup before downgrading.
- **Bad release:** CI gates (lint/type/tests/audit/migrations/container smoke) must pass before merge to `main`; rollback = previous green commit's image.

## 7. Known operational limits

- In-memory rate limiter is per-process → multi-worker/multi-replica needs Redis (documented).
- SQLite is single-node; move to Postgres before horizontal scaling.
- Real LLM providers require API keys (`LLM_PROVIDER=mock` default answers from corpus context).
- TLS termination belongs to the reverse proxy/load balancer, not the app.

## 8. Pre-production checklist

- [ ] Postgres + Redis provisioned; `DATABASE_URL` migrated; Alembic run against prod DB
- [ ] `JWT_SECRET` set to ≥32-byte random value; `ENV=production`; admin bootstrap credentials rotated
- [ ] RPO/RTO defined; automated backups scheduled and RESTORE TESTED
- [ ] Prometheus/Grafana/alerting wired to `/metrics`
- [ ] Load test at expected concurrency (locust/k6) executed
- [ ] Reverse proxy TLS enforced; security headers reviewed
