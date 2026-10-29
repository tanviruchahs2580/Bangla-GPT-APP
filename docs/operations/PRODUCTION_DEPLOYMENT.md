# PRODUCTION DEPLOYMENT — Bangla-GPT-APP

> **Date:** 2026-09-14
> **Current production:** Vercel SPA; the API origin is supplied per-deployment
> through the `API_ORIGIN` variable of the `apps/web/api/[[...path]].ts` edge
> proxy (no origin or tunnel hostname is baked into the repo — see README.md).

---

## 1. Environments

| Environment | Frontend | API | Database | Redis |
|-------------|----------|-----|----------|-------|
| **Development** | `npm run dev` (Vite,:5173) | `uvicorn` (localhost:8000) | SQLite file | Optional (memory rate limiter) |
| **Staging** | Vercel preview | Docker Compose (profile: core) | PostgreSQL 16 | Redis 7 |
| **Production** | Vercel (bangla-gpt-app.vercel.app) | VM/Docker + Caddy TLS | PostgreSQL 16 (RDS/Cloud SQL) | Redis 7 |

---

## 2. Reproducible Build

### API

```bash
# Build Docker image (same as CI). There is no APP_VERSION build-arg: the
# image is version-independent and the release tag drives the tags and the
# metadata labels (release.yml). The version number's single source is
# apps/api/pyproject.toml, so derive it here instead of copying it.
VERSION="$(python3 -c 'import tomllib;print(tomllib.load(open("apps/api/pyproject.toml","rb"))["project"]["version"])')"
DOCKER_BUILDKIT=1 docker build \
  --tag "ghcr.io/tanviruchahs2580/bangla-gpt-app/api:v${VERSION}" \
  --push .
```

**Dockerfile:** Single-stage runtime image on a digest-pinned
`python:3.12-slim` base (`Dockerfile:11`), non-root uid 10001, with the
hash-verified dependency layer ordered BEFORE the source copy so source
changes do not invalidate it. (Only `apps/web/Dockerfile` is multi-stage:
node build → nginx.)

### Web

```bash
cd apps/web
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" npx vercel build --prod
# Output: dist/ with hashed assets
```

---

## 3. Deployment Steps

### Option A: Docker Compose (full stack)

```bash
# Full stack with all profiles
docker compose --profile core --profile worker --profile web \
  --profile postgres --profile monitoring --profile backup up -d

# Minimal (api + redis only)
docker compose --profile core up -d
```

**Required environment variables** (`.env.production.example`):
```
ENV=production
LLM_PROVIDER=gemini
GEMINI_API_KEY=<key>
DATABASE_URL=postgresql+psycopg://bgpt:bgpt@postgres:5432/bgpt
JWT_SECRET=<32+ char random string>
ALLOWED_ORIGINS=https://bangla-gpt-app.vercel.app
REDIS_URL=redis://redis:6379/0
DOMAIN=banggpt.app
ACME_EMAIL=admin@banggpt.app
ADMIN_EMAIL=<admin>
ADMIN_PASSWORD=<12+ chars>
```

### Option B: Vercel + Separate API host

1. **Frontend:** `npx vercel --prod` from `apps/web/`
2. **API:** Deploy to any VM/PaaS (Railway, Fly.io, AWS EC2, GCP VM)
3. **Point the edge proxy at it:** set the `API_ORIGIN` project environment
   variable in Vercel (the proxy `apps/web/api/[[...path]].ts` reads it;
   `apps/web/vercel.json` contains no API destination). Until it is set,
   `/api/*` answers 503 `api_origin_unconfigured` by design.
4. **Reroute DNS:** Point custom domain to Vercel

### Option C: GHCR pull (verified in CI)

```bash
# The released tag carries the version from apps/api/pyproject.toml (0.9.3
# today). Derive the tag so this page cannot drift from the manifests.
VERSION="$(python3 -c 'import tomllib;print(tomllib.load(open("apps/api/pyproject.toml","rb"))["project"]["version"])')"
docker pull "ghcr.io/tanviruchahs2580/bangla-gpt-app/api:v${VERSION}"
docker pull "ghcr.io/tanviruchahs2580/bangla-gpt-app/web:v${VERSION}"
```

---

## 4. Startup Validation

All of these must pass for a successful deployment:

| Check | Endpoint/Command | Expected |
|-------|-----------------|----------|
| Health | `GET /health` | 200 `{"status":"ok"}` |
| Liveness | `GET /live` | 200 |
| Readiness | `GET /ready` | 200 if all configured providers are available |
| DB migration | `alembic upgrade head` | No errors |
| Admin creation | On first boot (if ADMIN_EMAIL + ADMIN_PASSWORD set) | Admin user created |

---

## 5. Security Configuration

| Setting | Dev | Prod |
|---------|-----|------|
| TLS | Optional (Caddy) | Required (Caddy auto-HTTPS) |
| CORS | `http://localhost:5173` | Vercel domain only |
| JWT_SECRET | `dev-insecure-change-me` (`config.py` default) | 32+ char random |
| PASSWORD_RESET_TOKEN_MINUTES | 30 | 30 |
| FORCE_ADMIN_PASSWORD_CHANGE | true | true |
| MAX_BODY_BYTES | 4000000 (4MB) | 4000000 (4MB) |
| LLM_TIMEOUT_SECONDS | 30 | 30 |
| LLM_MAX_RETRIES | 2 | 2 |
| CIRCUIT_BREAKER_FAILURE_THRESHOLD | 3 | 3 |
| RATE_LIMIT_LOGIN_PER_MINUTE | 10 | 10 |
| RATE_LIMIT_TUTOR_PER_MINUTE | 30 | 30 |

---

## 6. Reverse Proxy Configuration

**Caddyfile** (`deploy/caddy/Caddyfile`):
```
domain {
    encode zstd gzip
    # Security headers (HSTS, X-Content-Type-Options, X-Frame-Options DENY)
    header {... }

    # API proxy: strip /api prefix
    handle_path /api/* {
        reverse_proxy api:8000
    }

    # SPA: hashed assets + client routes
    handle {
        header "Content-Security-Policy" "default-src 'self';..."
        reverse_proxy web:80
    }
}
```

---

## 7. Monitoring & Alerting

| Tool | Config | Purpose |
|------|--------|---------|
| Prometheus | `deploy/prometheus/prometheus.yml` | Metrics collection |
| Grafana | `deploy/grafana/dashboards/bangla-gpt.json` | Dashboards |
| Sentry | `configure_observability_with_sentry()` | Error tracking |

**Key alerts** — the threshold each rule actually ships with in
`deploy/prometheus/alerts.yml` (also listed in `docs/runbook.md` §5):

- `HighHTTP5xxRate` — >2% 5xx for 5 min (critical)
- `HighP95Latency` — p95 > 1s for 10 min (warning)
- `APIScrapeDown` — Prometheus scrape target down for 2 min (critical)
- `UnhandledExceptions` — any unhandled exception in the last 10 min (warning)
- `DiskNearFull` — disk >80% for 15 min (warning; needs node_exporter)

---

## 8. Rollback Procedure

### Frontend (Vercel)

```bash
# Revert to previous deployment
npx vercel rollback
```

### API (Docker)

```bash
# Pull and restart with the previous image tag (the tag the previous release
# shipped -- read it from the git tags, never from a number in this document)
docker pull ghcr.io/tanviruchahs2580/bangla-gpt-app/api:<previous-release-tag>
# Update docker-compose.yml or deployment config
docker compose up -d api
```

### Database (Alembic)

```bash
# Rollback one migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade <revision>
```

**Note:** Since migrations are append-only, rollback is safe for data migration
reversibility but not for schema downgrades involving data loss. The revision to
downgrade to is whatever `alembic heads` / `alembic history` prints for the
deployed database — never a value copied from a document, including this one.

---

## 9. Smoke Tests (post-deploy)

```bash
# Run from repo root
bash scripts/smoke.sh
```

Validates:
1. `/health` → 200
2. `/ready` → 200 (if provider configured)
3. User registration (write path)
4. Login → JWT token
5. Learn endpoint → structured answer
6. Tutor grounded Q&A → cited sources
7. Quiz start → submit → result
8. Me page → profile data
9. Data export → success
10. Account deletion → success

---

## 9a. What a fresh host must have (verified 2026-10-26)

Everything below was measured while bringing the live deployment onto the
current code, and each line is a failure that actually happened.

**The API refuses to boot on a production-strict config that is missing any of
these** (`initialize/dependencies.py`), by design — the message names the
field:

| Missing | The guard says | Why it refuses |
|---|---|---|
| `JWT_SECRET` (>= 32 chars) | — | sessions would be forgeable |
| `ADMIN_PASSWORD` | — | bootstrap credentials |
| `PII_ENC_KEY` | "PII_ENC_KEY must be set in production (guardian phone encryption)" | guardian phone numbers are Fernet-encrypted |
| `SMTP_ENABLED` + `SMTP_HOST` + `SMTP_FROM` | "SMTP must be configured in production ... otherwise email verification is bypassed" | verification is the only proof the address is real |
| `METRICS_REQUIRE_AUTH=true` | "METRICS_REQUIRE_AUTH must be true in production (/metrics must not be public)" | `/metrics` leaks usage shape |

**Order matters on Postgres: migrate, then start.** The app does NOT create
tables in production-strict environments (`_safe_init_db` returns early when
`is_production` and the URL is postgres) — that is deliberate, so a schema
change is always a reviewed migration. Starting the API before
`alembic upgrade head` therefore gives you workers that fail to boot against an
empty schema:

```bash
docker compose run --rm --no-deps api sh -c "cd /app/apps/api && alembic upgrade head"
docker compose --profile core --profile postgres --profile web up -d
```

**The corpus is not optional.** Without `NCTB_CORPUS_DIR` pointing at a mounted
corpus the app falls back to a sample corpus and the tutor refuses nearly every
question ("উত্তরটি পাঠ্যবইয়ের বিষয়বস্তুর ভিত্তিতে দেওয়া সম্ভব নয়") — a correct
refusal for the wrong reason. Mount it and confirm the log line
`rag_corpus_loaded` reports the real chunk count (2599 on the current corpus).

**`LLM_PROVIDER` must not stay at its default.** `mock` is the code default and
it answers with canned text; production needs `LLM_PROVIDER=gemini` plus
`GEMINI_API_KEY`/`GEMINI_MODEL`, and the Play data-safety record asks for a
**paid** tier because the free tier uses submitted content for product
improvement.

**`SSL_CERT_FILE` must be a bundle, not a single cert.** It was pointed at the
self-signed certificate of the local SMTP (mailpit) so STARTTLS would verify;
the side effect was that **every outbound HTTPS call failed**, which surfaced as
`502 llm_unavailable` on every ask while `/status` still reported the assistant
as configured. Build the trust store as the image's CA bundle plus the private
cert:

```bash
cat /etc/ssl/certs/ca-certificates.crt /certs/cert.pem > /data/ca-bundle.pem
# SSL_CERT_FILE=/data/ca-bundle.pem
```

**A fresh account cannot log in until it verifies its email**, so
`scripts/smoke.sh` and `scripts/concurrency_probe.py` need a way to complete
that: the probe takes `--mailpit http://127.0.0.1:8025` (or
`--email/--password` for an account that is already verified). The smoke script
expects a development environment that auto-verifies.

**Load numbers from that host shape** (2 workers, Postgres + Redis, corpus
loaded, laptop-grade CPU): the concurrency probe reports **0% errors at 1, 5, 10
and 25 concurrent** mixed ask/read requests, p50 51 ms → 1.7 s and ~14 rps at 25
concurrent — the ask path (retrieval + provider) is the cost, and the rate
limiter, not the app, is what a probe hits first unless its ceilings are raised
on the load target.

## 10. Known Operational Caveats

1. **The web app has no origin of its own.** The Vercel edge proxy forwards
   `/api/*` to whatever `API_ORIGIN` names, so the API side must be reachable
   at a stable address; a rotating quick-tunnel hostname is explicitly not
   suitable for permanent production. Migrate the API to a VM or PaaS and
   give it a stable origin.
2. **The origin is configuration, not a file.** Changing it means updating the
   `API_ORIGIN` environment variable in the Vercel project (and redeploying).
   `apps/web/vercel.json` holds no API destination to edit.
3. **The code default LLM provider is `mock`.** Production must set
   `LLM_PROVIDER`/key for real AI responses; the shipped template
   (`.env.production.example`) sets `LLM_PROVIDER=gemini`.
