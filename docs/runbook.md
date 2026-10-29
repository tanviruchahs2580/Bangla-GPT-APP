# Operations Runbook — Bangla GPT APP

Audience: engineer/SRE deploying or operating the platform.

Commands that run on a development machine were executed against this tree on
2026-10-29: start/stop (§1), the migration cycle (§3), backup + restore (§4),
the rolling-deploy demo (§3), the JWT rotation (§10). Commands that need a
deploy host, an SSH key, Vercel or Cloudflare credentials are marked host-side
and were verified against the workflow/config that implements them, not run.

## 1. Start locally (dev)

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
# optional persistent DB:
#   set DATABASE_URL=sqlite:///./bangla_gpt.db
#.venv\Scripts\alembic upgrade head
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

Web dashboard (dev): `cd apps/web && npm ci && npm run dev` → http://localhost:5173
(dev server proxies `/api/*` to `http://127.0.0.1:8000`). Production build: `npm run build`.

## 2. Staging / production deployment (docker compose)

Full topology lives in `docker-compose.yml` with profiles:

```bash
cp .env.production.example .env    # fill every required value first!
docker compose --profile core up -d --wait          # api + redis (shared Redis limiter)
docker compose --profile core --profile web --profile tls up -d --wait   # + nginx dashboard + Caddy auto-HTTPS
docker compose --profile monitoring up -d           # Prometheus (+ Grafana)
```

- `ENV=production` (and `ENV=staging` — parity: staging runs the same
  strict guard) boot guard refuses to start with a default/short `JWT_SECRET`,
  missing `ADMIN_EMAIL/ADMIN_PASSWORD`, or an `ADMIN_PASSWORD` shorter than 12 chars.
- Env-surface drift is mechanically guarded: `pytest apps/api/tests/test_env_parity.py`
  fails if `.env*.example` documents a variable with no `Settings` field (or vice
  versa outside the explicit INFRA_ONLY compose/build list), or if
  `docker-compose.yml` interpolates a variable that is neither documented in
  `.env.production.example` nor defaulted inline. New deploy vars MUST be added
  to one of those two places.
- The API is published to the host on `127.0.0.1:8000` by default — loopback
  only, which is what a host-side tunnel or a `curl 127.0.0.1:8000/health` from
  the host uses. `API_HOST_PORT` moves the port, `API_HOST_BIND` widens the
  interface; `0.0.0.0` exposes the API to the network and nothing in the stack
  authenticates a client at that layer, so set it only when a remote tunnel
  genuinely requires it. The release workflow's own gate does not use this
  mapping — it reads the api container's healthcheck, so a healthy release
  passes whether or not the port was published.
- Caddy and nginx reach the API as `api:8000` on the Compose network and never
  use that host mapping.
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

Image is python:3.12-slim (pinned by digest), runs as non-root `appuser`
(uid/gid 10001), HEALTHCHECK on `/health`, and serves gunicorn+uvicorn workers
(`WEB_CONCURRENCY`, default 2).

### Deploying a release (tag push) and the secrets it needs

Pushing `vX.Y.Z` builds and pushes both images, creates a GitHub Release, and
deploys over SSH when `vars.DEPLOY_ENABLED == 'true'`. Four secrets are
required; without them the deploy job skips cleanly.

| Secret | Purpose |
| --- | --- |
| `DEPLOY_HOST` | SSH host or IP of the deploy target |
| `DEPLOY_USER` | SSH user on that host |
| `DEPLOY_SSH_KEY` | Private key for that user (add the public key to `~/.ssh/authorized_keys`) |
| `DEPLOY_HOST_FINGERPRINT` | `SHA256:...` fingerprint of the host's SSH key |

**The host fingerprint is mandatory, not optional.** Without it the SSH client
accepts whatever key the host presents, so anyone able to intercept the
connection could impersonate the deploy host and receive the commands that
carry out a release. The release workflow refuses to deploy when the secret is
missing or malformed rather than silently skipping verification.

Obtain it from the host, and record where you got it from:

```bash
# run ON the deploy host, or against it from a trusted network:
ssh-keyscan -p 22 deploy.example.com 2>/dev/null | ssh-keygen -lf -
# e.g. 256 SHA256:0ZC1x0KQ3dEXAMPLEkeymaterial... deploy.example.com (ED25519)

# verify it out-of-band before trusting it: compare with the fingerprint the
# host itself reports, e.g. `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`
```

Store the `SHA256:...` string (and nothing else) as the repository secret
`DEPLOY_HOST_FINGERPRINT`, then confirm the deploy job's summary shows
`Deploy-host fingerprint present`.

**Rotating the host key.** If the fingerprint in the secret does not match,
the deploy fails closed — that is the intended behaviour, not a bug. Confirm
the new key through a second channel, update the secret, and re-run the tag.

### End-to-end stack smoke

End-to-end stack smoke (executed inside the api container):

```bash
docker cp scripts/smoke_stack.py <api-container>:/tmp/smoke_stack.py
docker compose exec -T api python /tmp/smoke_stack.py   # expect SMOKE OK
```

### Scheduled background jobs: inline vs ARQ

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

### Expand–contract convention (required for zero-downtime deploys)

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
`python scripts/deploy_rolling.py --ready-url <new /ready URL> --reload-cmd
"<proxy upstream switch>" [--drain-cmd "<old instance stop>"]` starts the new
release alongside the old, polls `--ready-url` until ready
(boot guard + index built), flips the front proxy upstream atomically, then
drains the old instance via `--drain-cmd`. If `/ready`
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
(`integrity_check: ok`, row counts verified, exit 0). Rehearsed again
2026-10-23 against the **live** SQLite stack (the single-container setup, which
has no compose profile):

```bash
docker run -d --name bgpt-backup-live --restart unless-stopped \
  -e DATABASE_URL=sqlite:////data/app.db -e BACKUP_DIR=/backups \
  -e BACKUP_INTERVAL_SECONDS=86400 -e BACKUP_KEEP_DAYS=14 \
  -v api-live-data:/data:ro -v bgpt-live-backups:/backups \
  -v "$PWD/scripts:/srv/scripts:ro" \
  --entrypoint python bangla-gpt-api:<tag> /srv/scripts/backup_loop.py

# then prove the newest snapshot restores:
docker run --rm -v bgpt-live-backups:/backups -v "$PWD/scripts:/srv/scripts:ro" \
  --entrypoint python bangla-gpt-api:<tag> /srv/scripts/restore_test.py --backup-dir /backups
# PASS: backup restores and queries cleanly (integrity ok, row counts printed)
```

The API image now ships `postgresql-client` (pg_dump), so the same loop works
for the Postgres profile — before that the loop logged
`pg_dump binary not found` every cycle and swallowed it.

## 5. Health checks, metrics & alerting

| Probe | Meaning | Action if failing |
|---|---|---|
| `GET /health` 200 | process up | restart container / check logs |
| `GET /live` 200 | request loop alive | orchestrator should restart |
| `GET /ready` 200 | DB reachable AND provider configured | 503 with provider message → fix `LLM_PROVIDER`; 503 `Database unavailable` → check DB path/volume |
| `GET /metrics` | Prometheus series | scraped by Prometheus (monitoring profile) |

**The scrape must authenticate.** Production sets `METRICS_REQUIRE_AUTH=true`,
so `/metrics` answers 403 without the token; the scrape config therefore reads
the token from a file (`bearer_token_file: /etc/prometheus/metrics_token`).
Create it before starting the monitoring profile:

```bash
printf '%s' "$METRICS_TOKEN" > deploy/prometheus/metrics_token   # git-ignored
docker compose --profile core --profile monitoring up -d
```

Without this the scrape failed every time, `up` stayed 1 on the 403, and every
`bgpt_*` alert evaluated against no data — the production outages in this
project's history were found by users, not monitoring.

**Alerts must have somewhere to go.** `deploy/alertmanager/alertmanager.yml`
emails the `ALERT_EMAIL_TO` address using the same SMTP settings the API uses
(`--config.expand-env=true`). Set `ALERT_EMAIL_TO` in the host `.env`, or
read the alertmanager container log to see delivery failures — a route to
nowhere is worse than no route, and this one fails loudly.

Alert rules ship in `deploy/prometheus/alerts.yml`:

- `HighHTTP5xxRate` — >2% 5xx for 5 min (critical)
- `HighP95Latency` — p95 > 1s for 10 min (warning)
- `APIScrapeDown` — scrape target down 2 min (critical)
- `UnhandledExceptions` — any unhandled exception increase
- `DiskNearFull` — requires node_exporter (fires only when present)
- `HighRAGRefusalRate` — the evidence gate refuses >50% of grounded attempts
  for 15 min (warning). The corpus-degradation signal (for example a mis-set
  `NCTB_CORPUS_DIR` leaving the 78-chunk bundled sample): check
  `bgpt_rag_index_chunks` and the `rag_corpus_loaded` boot line first, then §8.
- `RAGCitationCheckFailures` — a grounded answer failed citation verification
  in the last 15 min (warning). Inspect the `ai_call` / `tutor_retrieval` logs
  for the request id.

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
3. TOTP/MFA **is** implemented: `POST /auth/mfa/enroll` then
   `POST /auth/mfa/verify` to enable it; `POST /auth/mfa/challenge` then
   `POST /auth/mfa/verify` to satisfy it at login; `POST /auth/mfa/disable` to
   turn it off. Until MFA is enabled for an account, restrict `/admin/*` at
   the reverse proxy or VPN layer.

## 7. Rollback

- **Release rollback:** redeploy the previous tag. The image tags are what
  select the release — `api` and `web` resolve to `${API_TAG:-local}` and
  `${WEB_TAG:-local}`, so both must be exported or `docker compose pull` goes
  looking for a `:local` tag that the registry does not have, and the `&&`
  chain stops before anything is deployed:

  ```bash
  cd /opt/bangla-gpt
  git fetch --tags --force origin
  git checkout vX.Y.Z
  export API_TAG=vX.Y.Z WEB_TAG=vX.Y.Z
  docker compose --profile core pull
  docker compose --profile core up -d --wait --wait-timeout 120
  ```

  The release workflow performs this automatically, on a failed `compose up`
  **and** on a failed post-deploy health gate. Before 2026-10-17 only the first
  of those paths rolled back: this section described a health-gated rollback
  that the workflow did not implement.
- **DB rollback:** `alembic downgrade <revision>` (verified cycle). Always take
  a backup (§4) before downgrading.
- **Rehearse the release rollback** (host-side, needs two tags and a staging
  stack): `scripts/rollback_drill.sh [CURRENT_TAG]` runs the workflow's exact
  sequence — checkout the previous tag, `compose pull`, `compose up --wait` —
  against a staging project and asserts the previous release comes up healthy.
  It is the drill for the rollback path release.yml performs automatically.
- **Bad release prevention:** CI gates (lint/format/type/tests/pip-audit/
  migrations incl. Postgres/golden-eval/container smoke) must pass before merge.

## 8. Known operational limits

- Redis rate limiting uses fixed 60 s `INCR`/`EXPIRE` windows (the in-process
  `memory` backend is a sliding window); counts are approximate under heavy
  skew (standard trade-off vs a sliding-window log).
- `RATE_LIMIT_FAIL_OPEN=false` (default) answers **503** on protected routes if
  Redis is down; set `true` to prefer availability over strictness.
- caches (`/dashboard/summary` 60 s per user; RAG query results 5 min,
  SHA-256 hashed keys -- never the raw question) share the same
  `RATE_LIMIT_BACKEND=redis` switch: `redis` -> all pods share the caches,
  otherwise a bounded in-process cache. Redis failure never breaks a request;
  caches degrade to a miss. Expect up to 60 s of staleness on the home
  dashboard after a quiz is graded (spec'd cache window).
- Third-party images are digest-pinned (compose, both Dockerfiles, the CI
  scanner). Digests never move on their own: refresh them deliberately with
  `python scripts/update_image_digests.py --write` (Dependabot cannot bump a
  digest pin) and commit the result.
- SQLite is single-node; move to Postgres before horizontal scaling.
- Live Gemini behaviour needs a real `GEMINI_API_KEY`; contract tests cover the
  client, live latency/quota behaviour is UNVERIFIED until a key is deployed.
- Textbook (পাঠ্যপুস্তক) OCR ingestion is implemented behind a permission gate
  (`BGPT_OCR_CONFIRMED=yes`) pending rights-holder permission.
- The Vercel web app proxies `/api/*` through its edge function
  (`apps/web/api/[[...path]].ts`) to the origin named by the `API_ORIGIN`
  project environment variable; `apps/web/vercel.json` only routes
  `/api/(.*)` to that function and contains no host. No tunnel URL is baked
  into the repo: changing the origin means updating `API_ORIGIN` in the Vercel
  project and redeploying. Until it is set, `/api/*` answers 503
  `api_origin_unconfigured` by design.
- TOTP/MFA is implemented (§6). It is per-account opt-in: an admin who has not
  enrolled a TOTP secret signs in with a password alone, so keep `/admin/*`
  behind the reverse-proxy/VPN restriction until every admin has enrolled.

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

### Vercel deployment token

`VERCEL_TOKEN` is a repository secret consumed by `.github/workflows/vercel-deploy.yml`.
It has been the single point of failure for production web deploys: on 2026-10-11 the
token that last succeeded on 2026-10-06 was rejected, every deploy since has failed at
the `Deploy (production)` step, and the post-deploy smoke check never ran.

A rejection is Vercel-side, not GitHub-side. GitHub reported no change to the secret
after 2026-10-06T19:36Z, and the deploys at 19:39 and 20:07 that same day succeeded with
it. So when this happens, the token was revoked or expired in Vercel; re-saving the same
value in GitHub will not fix it.

To rotate:

1. Mint a new token: Vercel dashboard → account Settings → Tokens → Create. Scope it to
   the team that owns `bangla-gpt-app` and grant only what `vercel deploy --prod` needs.
2. Revoke the old token in the same screen. Do this second, after the new one is
   confirmed working, so a bad mint does not leave the project with neither.
3. Update the repository secret:
   `gh secret set VERCEL_TOKEN --repo tanviruchahs2580/Bangla-GPT-APP`
4. Re-run the deploy. The workflow's `Preflight: deployment credentials` step calls
   `vercel whoami` before doing any work, so a bad token now fails in seconds with a
   named cause instead of after a full `npx` download.
5. Verify the alias: `curl -s -o /dev/null -w '%{http_code}\n' https://bangla-gpt-app.vercel.app/login`
   must return 200.

Note that this token deploys with whatever `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` point
at. Those are also repository secrets and neither has been rotated; if the Vercel project
was ever recreated under a new team, rotate all three together rather than one at a time.

### API origin down: diagnose and rotate the tunnel

**Symptom.** Nobody can log in — including from a phone, which is where it is usually
noticed first. Every `/api/*` call through the alias answers `502
{"code":"api_origin_unreachable"}` and the app shows "the server isn't responding"; the
static pages still load, so the deployment looks healthy.

**Cause.** The API origin behind the edge proxy is an ephemeral `cloudflared` quick
tunnel. When Cloudflare invalidates it the hostname stops resolving entirely (DNS
NXDOMAIN, not just a refused connection) while the Vercel `API_ORIGIN` variable keeps
pointing at it. `apps/web/vercel.json` holds no host, so nothing in the repo can see the
breakage. Rotation is a recurring chore in the audit trail (Sept–Oct 2026); on 2026-10-26
the probe went red at 01:13 and the origin was repaired at 07:00.

**Confirm it** (one request; `502` means the origin, `200` means look elsewhere):

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://bangla-gpt-app.vercel.app/api/health
```

The scheduled probe (`.github/workflows/uptime.yml`) checks exactly this every 15 min and
fails in Actions. Do not rely on it for detection latency: GitHub throttles schedules
hard (2026-10-26: runs at 01:13 and 06:16, a five-hour gap on a `*/15` cron).

**Repair** (verified 2026-10-26, Windows/Git Bash; `$URL` becomes a fresh hostname):

```bash
# 1. A quick tunnel mints a NEW hostname on every start; the old one is gone for good.
docker rm -f api-tunnel
docker run -d --name api-tunnel --restart unless-stopped \
  --add-host=host.docker.internal:host-gateway \
  cloudflare/cloudflared:latest \
  tunnel --no-autoupdate --protocol quic --url http://host.docker.internal:8000

# 2. Read the hostname it registered (wait for "Registered tunnel connection").
URL=$(docker logs api-tunnel 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1)

# 3. Prove the origin serves the API before pointing anything at it.
curl -fsS "$URL/health"    # {"status":"ok"}

# 4. Point production at it. Bare origin, no /api suffix — the edge proxy strips /api.
printf '%s' "$URL" | vercel env add API_ORIGIN production   # after: vercel env rm API_ORIGIN production --yes

# 5. Env changes only apply to NEW deployments. Redeploy the current production
#    deployment (top row of `vercel ls --prod`), or push to main to take the
#    CI-gated path in .github/workflows/vercel-deploy.yml.
vercel redeploy bangla-gpt-<hash>-<team>.vercel.app --target production
```

Deploy-CLI gotchas on this machine, both hit on 2026-10-26: `vercel --prod` run from
`apps/web` fails with a doubled path (`The provided path "~\projects\...
\apps\web\apps\web" does not exist`) because the linked project already carries
`rootDirectory: apps/web`; run it from the repo root instead, where it then needs
`--archive=tgz` (the tree exceeds Vercel's 15000-file limit). `vercel redeploy
<deployment-or-alias-url> --target production` avoids both and is the shortest path.
`HOME` may need to be set to a Windows-style path (`HOME='C:/Users/<you>'`) for any
`vercel` subcommand that resolves paths.

**Verify the repair — login, not just health:**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://bangla-gpt-app.vercel.app/api/health   # 200
curl -sS -X POST https://bangla-gpt-app.vercel.app/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"nobody@example.com","password":"wrong-password-123"}' \
  -w '\n%{http_code}\n'                                                                   # 401 bad_credentials
```

A 401 with `bad_credentials` proves the whole chain (DNS → TLS → tunnel → proxy → API →
auth); a 502 means the origin is still dead.

**Same symptom, local cause.** `http://127.0.0.1:8081/api/*` 502s when the API container
is not reachable under the name the preview's nginx proxies to (`api:8000`). A container
started by hand as `api-live` needs that alias or every local `/api` call fails while the
API itself is healthy:

```bash
docker network connect --alias api bgpt-live api-live   # after: docker network disconnect
```

**A rotated origin breaks native builds.** An APK bakes `VITE_API_BASE` at build time, so
it keeps calling the dead hostname until it is rebuilt and `npx cap sync`ed
(`docs/mobile_release.md`). Existing installs cannot be repaired server-side.

**Durable fix (not yet authorized).** A named tunnel or a VM/PaaS address makes the origin
stable and removes this whole failure class; it needs the budget and residency sign-off
recorded in `docs/hosting_decision.md`.

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

### Support ops & SLA
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

## 11. Incident first response (common incidents)

Triage by symptom; each row names the first check and the section that carries
the procedure.

| Symptom | First check | Then |
|---|---|---|
| Nobody can log in | `curl -s -o /dev/null -w '%{http_code}\n' https://bangla-gpt-app.vercel.app/api/health` — `502` is the origin, `200` means look elsewhere | §10 "API origin down" (rotate the tunnel), or §7 (roll back a bad release) |
| `HighHTTP5xxRate` / `APIScrapeDown` firing | `docker compose --profile core logs api`; every line carries `X-Request-ID` | §5, §7 |
| `/ready` 503 `database_unavailable` | SQLite volume present / `pg_isready` for the Postgres profile | §4, §3 |
| `/ready` 503 naming the provider | Confirm `LLM_PROVIDER` and its key; a provider outage answers `/tutor/ask` 502 `llm_unavailable` while `/ready` stays 200 | §8, §10 (key rotation) |
| Protected routes answering 503 | Redis down and `RATE_LIMIT_FAIL_OPEN=false` fail closed by design | §8; restart `redis`, or accept the outage |
| `DiskNearFull` or write errors | `df -h` on the host and in the container; prune backups beyond `BACKUP_KEEP_DAYS` | §4 |
| Backup missing or restore rehearsal red | `docker compose logs backup`; rerun `restore_test.py` | §4 |
| Release deployed, behaviour wrong | Redeploy the previous tag | §7 |
| Suspicion that children's data was exposed | Preserve evidence (do not delete logs or the DB volume) | Report per [SECURITY.md](../SECURITY.md) with "data incident" in the subject — this table does not cover data incidents |
| Unsafe AI answer, or generation must stop | Decide whether to disable generation (`AI_GENERATION_ENABLED=false`, restart `api`) | [ai/incident-response.md](ai/incident-response.md) |

Detection latency: the scheduled uptime probe is best-effort — GitHub throttles
`schedule` runs, and 2026-10-23..28 saw 35 runs (2-7 per day) instead of the
nominal every 15 min, so a failure can be noticed hours late. The workflow's
`page` job files a deduplicated issue and `resolve` closes it on the next green
probe. Treat the probe as a backstop, not a pager.

After any incident, record what happened, the impact and the follow-up action
in the current QA record or a follow-up issue; do not edit an archived report
to match the new facts.
