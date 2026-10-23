# Deploying the API to a real host

**Why this document exists.** Production is currently down because `API_ORIGIN`
points at a Cloudflare quick tunnel that reaches `host.docker.internal:8000` —
a laptop — running `ENV=test`, `LLM_PROVIDER=mock`, with an empty SQLite
database. The tunnel is dead, and it should stay dead: reviving it would point
production at a mock-LLM, empty-database, test-mode application, served from a
developer machine over the public internet, to real users of a children's
education product. An honest 502 is better than that.

Quick-tunnel hostnames also rotate, which is what broke production twice
already (`0a4bec2`, `7d04b14`). The architecture, not the credential, is the
problem.

This guide deploys the API image to a host you control, on a domain that does
not move.

---

## 1. What you need before starting

| Requirement | Why |
|---|---|
| A host: a VPS, a PaaS container service, or a Kubernetes node | The API must not run on a developer's machine |
| A domain or subdomain, e.g. `api.tutor.example.edu.bd` | `API_ORIGIN` is baked into the web bundle at build time; a stable name is required |
| PostgreSQL 14+ reachable from the host | SQLite is refused in production with `WEB_CONCURRENCY > 1` — two gunicorn workers contend on one file |
| Redis | `RATE_LIMIT_BACKEND=redis` is required in production; the memory backend multiplies every limit by the worker count |
| A real LLM provider key (Gemini or OpenAI) | `LLM_PROVIDER=mock` is refused in production unless you set the deliberate offline-demo escape hatch |
| An SMTP relay | Email verification is skipped when SMTP is absent, so every account is auto-trusted |

Budget for roughly 1 GB RAM and 2 vCPU at low traffic. The tutor is the only
expensive part, and its concurrency is bounded by
`RATE_LIMIT_TUTOR_PER_MINUTE`.

## 2. The order that matters

Do these in this order. Each step has a check, and the check is the point —
several of these fail *silently* in the wrong order.

1. Provision the host and the domain.
2. Provision PostgreSQL and Redis.
3. Run the migrations against that database.
4. Set the secrets. **Generate them; do not invent them.**
5. Start the API. Confirm it boots at all.
6. Put a TLS-terminating proxy in front.
7. Point the web app's `API_ORIGIN` at it and redeploy the web app.
8. Turn on the remaining production guards in GitHub (F-001, F-021).

Step 5 before step 7 matters: if you deploy the web app first, users get a
login page that cannot complete, and the smoke check will not tell you why.

## 3. Provision the host

Any Linux host with Docker and Compose v2 works. On Debian/Ubuntu:

```bash
# Docker + compose plugin
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker

# A non-root deploy user with a stable home
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo mkdir -p /opt/bangla-gpt && sudo chown deploy:deploy /opt/bangla-gpt
```

`/opt/bangla-gpt` is where the deployment lives. Nothing is ever written to the
repository checkout except `.env`, which never leaves the host.

## 4. Database and Redis

```bash
docker run -d --name bgpt-postgres \
  -e POSTGRES_USER=bgpt -e POSTGRES_DB=bgpt \
  -e POSTGRES_PASSWORD="$(openssl rand -base64 32)" \
  -p 127.0.0.1:5432:5432 \
  -v bgpt-pgdata:/var/lib/postgresql/data \
  postgres:16-alpine

docker run -d --name bgpt-redis \
  -p 127.0.0.1:6379:6379 \
  redis:7-alpine redis-server --appendonly yes \
  --requirepass "$(openssl rand -base64 32)" \
  -v bgpt-redisdata:/data
```

Both bind to `127.0.0.1` on purpose: they are reachable from the host and
nothing else. If you use a managed service instead, put it behind a private
network and a firewall rule that rejects everything but the API host.

## 5. Get the image and run the migrations

The image is either pulled from the registry or built on the host. Pushing a
`vX.Y.Z` tag makes `release.yml` publish both images to GHCR, gated on a green
CI run for that commit, so pulling a released tag is the shorter path:

```bash
cd /opt/bangla-gpt
git fetch --tags --force origin
git checkout vX.Y.Z                    # never deploy a moving ref
export API_TAG=vX.Y.Z WEB_TAG=vX.Y.Z   # the tags select the image; without
                                       # them compose resolves `:local`
docker compose --profile core pull
docker compose --profile core up -d --wait
```

To build from source instead, build on the host from the repository root:

```bash
cd /opt/bangla-gpt
git clone --branch main https://github.com/tanviruchahs2580/Bangla-GPT-APP.git app
cd app
git checkout <the-sha-you-are-deploying>     # never deploy a moving ref
docker build -t bangla-gpt-api:"$(git rev-parse --short HEAD)" .
```

Migrations must be applied before the app starts, against the production
database, once:

```bash
docker run --rm \
  -e DATABASE_URL="postgresql+psycopg://bgpt:<pw>@host.docker.internal:5432/bgpt" \
  -v /opt/bangla-gpt/app:/app -w /app/apps/api \
  bangla-gpt-api:<tag> \
  alembic upgrade head

# Verify the models and the migration history agree. This is a real check, not
# a formality: the upgrade cycle passes even when they disagree.
docker run --rm \
  -e DATABASE_URL="postgresql+psycopg://bgpt:<pw>@host.docker.internal:5432/bgpt" \
  -v /opt/bangla-gpt/app:/app -w /app/apps/api \
  bangla-gpt-api:<tag> \
  alembic check
```

`alembic check` must print *No new upgrade operations detected*. If it does
not, stop: the image and the migration history are out of step.

Take a backup before the first run, and again before every migration:

```bash
cd /opt/bangla-gpt/app
PGPASSWORD=<pw> pg_dump -h 127.0.0.1 -U bgpt bgpt \
  | gzip > "/opt/bangla-gpt/backups/bgpt-$(date -u +%FT%TZ).sql.gz"
```

`scripts/pg_backup.sh` (one-shot) and `scripts/backup_loop.py` (scheduled)
do this. `scripts/restore_test.py` restores a dump into a scratch database --
run it after the first backup, not on the day you need it.
Schedule it. An untested backup is not a backup.

## 6. Secrets

`.env` lives on the host with mode `600`, and never enters git. The production
guards are strict, and that is deliberate: several of them previously checked
only that a value was *present*.

```bash
install -m 600 /dev/null /opt/bangla-gpt/app/.env
```

```bash
# JWT_SECRET — the guard now checks entropy, not just length, so do not type
# one. 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' is refused.
printf 'JWT_SECRET=%s\n' "$(openssl rand -base64 48)"

# PII_ENC_KEY — must be a real Fernet key. A malformed value boots in older
# builds and then raises on the first guardian phone.
printf 'PII_ENC_KEY=%s\n' "$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"

# POSTGRES_PASSWORD / REDIS_PASSWORD
openssl rand -base64 32
```

The rest of the required values:

| Variable | Value | Guard |
|---|---|---|
| `ENV` | `production` | — |
| `DATABASE_URL` | `postgresql+psycopg://bgpt:…@host.docker.internal:5432/bgpt` | file SQLite refused with >1 worker |
| `ALLOWED_ORIGINS` | your web origin, comma-separated | empty and `*` are both refused |
| `LLM_PROVIDER` | `gemini` or `openai` | `mock` refused without the offline-demo escape hatch |
| `GEMINI_API_KEY` | the real key | required when the provider is `gemini` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | a real address, ≥12 characters | both required; short refused |
| `SMTP_*` | your relay | absent means email verification is silently skipped |
| `PII_ENC_KEY` | the Fernet key above | must parse |
| `METRICS_REQUIRE_AUTH` / `METRICS_TOKEN` | `true` / a random token | `/metrics` is never public in production |
| `RATE_LIMIT_BACKEND` / `REDIS_URL` | `redis` / `redis://:…@host.docker.internal:6379/0` | the memory backend is refused with >1 worker |

Rotating `PII_ENC_KEY` invalidates existing guardian-phone ciphertext. Re-encrypt
before you rotate; `docs/runbook.md` has the procedure.

## 7. Start the API and confirm it boots

```bash
cd /opt/bangla-gpt/app
docker compose --profile core up -d --wait
docker compose logs --tail 100 api
```

**If the container refuses to start, it is telling you something.** The boot
guard raises one combined `RuntimeError` naming every problem it found:

```
Refusing to start: insecure production configuration detected:
- JWT_SECRET is too predictable: it uses only 2 distinct characters
- PII_ENC_KEY is not a valid Fernet key (ValueError); generate one with ...
- RATE_LIMIT_BACKEND=memory is per-process and therefore per-worker;
  with WEB_CONCURRENCY=2 the effective limit is multiplied by the worker count
```

Fix what it names. Do not set `ALLOW_MOCK_LLM_IN_PRODUCTION` to get past it —
that flag exists for an offline demo and will serve fabricated answers to real
children.

Then confirm all three probes answer, and confirm they are *different* things:

```bash
curl -fsS https://api.example.edu.bd/health    # {"status":"ok"}    process alive
curl -fsS https://api.example.edu.bd/ready     # checks DB + provider  dependencies
curl -fsS https://api.example.edu.bd/live      # liveness only
```

`/ready` returning 200 is the one that means the service is actually usable. A
green `/health` with a red `/ready` is the exact shape of the outage this
repository is in.

## 8. TLS in front

The API image serves plain HTTP and expects a proxy to terminate TLS. HSTS is
correctly the proxy's job — see `deploy/caddy/Caddyfile`.

Minimum: HSTS (`max-age=31536000; includeSubDomains`), and the proxy forwards
`X-Forwarded-For`. The rate limiter reads that header only when
`TRUST_PROXY_HEADERS=true` (compose ships it true). That pairing is safe
because the bundled reference proxy **overwrites** the header with the address
it observed (`deploy/caddy/Caddyfile`: `header_up X-Forwarded-For {remote_host}`).
If you use a proxy that **appends** instead (nginx's
`$proxy_add_x_forwarded_for`, Caddy's default behaviour), set
`TRUST_PROXY_HEADERS=false` or make the proxy overwrite first: an appending
proxy plus the flag lets a client that sets its own `X-Forwarded-For` choose
its own rate-limit bucket. `apps/api/scripts/check_proxy_contract.py` fails CI
if this pairing drifts in the repository.

```bash
curl -I https://api.example.edu.bd/health | grep -i strict-transport-security
```

## 9. Point the web app at it, and redeploy

`API_ORIGIN` is read from the Vite environment **at build time** and baked into
the bundle. Changing it requires a redeploy of the web app; there is no runtime
switch.

1. Set `API_ORIGIN=https://api.example.edu.bd` as a Vercel environment variable
   for **Production**.
2. Redeploy. The deploy workflow runs only after the full CI gate is green on
   `main`.
3. Confirm with the check that actually matters — the web app's own proxy, not a
   static route:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://bangla-gpt-app.vercel.app/api/health
# 200 = the proxy reaches the origin.
# 502 = the proxy is live but the origin is not: read the workflow log, which
#       names the origin server-side and never sends it to the client.
```

A 200 on `/login` tells you nothing: that is a static asset served by the CDN
and it answers 200 through a total outage. This is the defect F-048, and the
smoke check in the deploy workflow now tests `/api/health` for that reason.

## 10. Turn on the production guards in GitHub

None of these are fixable from code; each needs a repository admin.

| Setting | Finding | Where |
|---|---|---|
| Secret scanning + push protection | F-001 | Settings → Code security → Secret scanning |
| Dependabot security updates | F-023 | Settings → Code security → Dependabot |
| Private vulnerability reporting | F-023 | Settings → General → Security |
| Branch protection on `main` | F-024 | Rules → Branches; require PR + 1 review |
| A production environment with required reviewers | F-021 | Vercel → Settings → Environments |
| A severity taxonomy for Dependabot | F-029 | the `gh label create` commands are in `.github/dependabot.yml` |

Three Vercel environments currently exist with overlapping names — `Production`,
`Production – bangla-gpt-app`, `Production – web` — all with empty
`protection_rules`. **Consolidate to one** and give it required reviewers, or
none of them is a gate.

## 11. Before you call it done

| Check | Expected |
|---|---|
| `GET /health`, `/live`, `/ready` | 200, 200, 200 |
| `GET /metrics` unauthenticated | 401 — never public |
| `POST /auth/login` with a bad password | 401 `bad_credentials`, same status as an unknown address |
| `POST /auth/register` ×12 from one IP | 429 by the 11th |
| `GET /admin/users` unauthenticated | 401 |
| Two schools, a teacher in each, cross-tenant id | 403 `other_school` |
| `GET /users/me/export` as a student | includes conversations and messages |
| HSTS on the API origin | present |
| `alembic check` | no new operations detected |
| A restore from last night's backup, into a scratch database | completes, and the row counts match |

That last one is the check people skip. Run it before you need it.

## 12. What this does not fix

Deploying the API to a real host makes production *reachable*. It does not
close the open findings. There is exactly one current record — the newest
`docs/qa/QA_REPORT_*.md` — and it carries the open-item register with its
severities and the reason each item was left open.

This paragraph used to restate those totals ("91 of the 130 recorded findings
remain open", with a "findings index" that exists nowhere in the tree, and ids
like F-078 that appear nowhere else). A second copy of a number is a number
that goes stale, and it had: the current record reports no open S0/S1/S2, and
the remainder are S3/S4 items. Read the record, not this file.

None of them make deploying unsafe. All of them make deploying premature for
scale. Deploy, then work the register.
