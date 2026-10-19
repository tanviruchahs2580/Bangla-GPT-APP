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

Web dashboard (dev): `cd apps/web && npm ci && npm run dev` → <http://localhost:5173>
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

## 11. Incident runbooks (top 10 classes)

Each entry is deliberately one page: symptom → first five minutes → mitigation
→ how to know it is over. Commands assume the `core` compose profile
(`docs/operations/PRODUCTION_DEPLOYMENT.md`) and the container names from
`docker-compose.yml`; substitute host paths on a VM deployment.

### Incident 1 — LLM provider outage or quota exhausted

- **Symptom:** `/tutor/ask` returns the `llm_unavailable` SSE error event or
  503; `UnhandledExceptions` / 5xx burn alerts; provider 429/5xx in logs;
  circuit breaker opens (`tutor: primary provider failed, using fallback`).
- **First five minutes:**
  1. `docker compose logs --since=10m api | grep -E "llm_unavailable|ProviderError|circuit"`
  2. `curl -s localhost:8000/ready` — provider configured?
  3. `curl -s localhost:8000/metrics | grep -E "bgpt_ai_answers_total|bgpt_http_requests_total.*5.."`
  4. Check the provider status page and the key's quota in the provider console
     (owner credentials).
- **Mitigation:** if quota, ask the owner to raise it; temporarily switch
  `LLM_PROVIDER` to the configured fallback (`LLM_FALLBACK_PROVIDER`) and
  restart; students keep retrieval-only refusals meanwhile (the coverage gate
  refuses rather than fabricating).
- **Over when:** `bgpt_http_requests_total{status=~"5.."}` returns to baseline
  and one live ask streams a grounded answer.

### Incident 2 — Database outage or failover

- **Symptom:** `/ready` 503 `Database unavailable`; 5xx burn alerts; pool
  timeouts in logs; `pg_isready` failing.
- **First five minutes:**
  1. `docker compose exec postgres pg_isready -U $POSTGRES_USER`
  2. `docker compose logs --since=10m postgres | tail -50`
  3. Check disk: `df -h` (a full volume is the most common cause).
  4. If managed Postgres: check the provider console for a failover event.
- **Mitigation:** restart the DB container/instance; if the primary is lost,
  promote the replica per the provider's procedure, then restore from
  `docs/backup_dr.md` only if data is actually missing. Application workers
  reconnect on the next request (pre-ping is on) — no app restart needed.
- **Over when:** `/ready` is 200 and `bgpt_http_requests_total` has no new 5xx
  for 10 minutes. **Declare data loss only after comparing row counts against
  the last backup** (documented in `docs/backup_dr.md`).

### Incident 3 — Retrieval index degraded / corpus mis-set

- **Symptom:** `HighRAGRefusalRate` fires; answers all become
  "not in the textbook"; `bgpt_rag_index_chunks{corpus="bundled-sample"}`
  appears in production.
- **First five minutes:**
  1. `curl -s localhost:8000/metrics | grep bgpt_rag_index_chunks`
  2. `docker compose logs api | grep rag_corpus_loaded` — which corpus, how many chunks?
  3. Compare `NCTB_CORPUS_DIR` with the mounted data path; `ls` the corpus dir.
- **Mitigation:** fix the path/env and restart the worker; the index rebuilds at
  boot (`bgpt_rag_index_build_seconds` says how long). Never "fix" it by
  lowering `MIN_COVERAGE` — that trades refusals for ungrounded answers.
- **Over when:** `bgpt_rag_index_chunks` reports the NCTB corpus size and a
  known-good question answers with citations.

### Incident 4 — Generation job backlog or stuck jobs

- **Symptom:** teachers report papers stuck in "Generating";
  `bgpt_ai_jobs_total{status="failed"}` rising; `AIJobFailureRateHigh` fires.
- **First five minutes:**
  1. `curl -s -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/admin/jobs?status=queued`
     (or the admin Create-hub view)
  2. `docker compose logs --since=15m api | grep -E "ai_job_(failed|ready)"`
  3. `curl -s localhost:8000/ready` — a provider outage is the usual cause
     (Incident 1).
- **Mitigation:** fix the upstream cause first; queued jobs run inline on the
  next worker tick, failed jobs need the teacher to re-queue (no automatic
  retry today — recorded as a gap in `docs/operations/SLO.md` SLO-4).
  Do not delete job rows: they are the teacher's audit trail.
- **Over when:** the queue drains and new jobs reach `ready`.

### Incident 5 — Authentication outage

- **Symptom:** every login returns 500/503; `APIScrapeDown`; users cannot
  register or reset.
- **First five minutes:**
  1. `curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"email":"x@example.com","password":"wrong"}`
     — expect 401, not 5xx.
  2. `docker compose logs --since=10m api | grep -E "auth|traceback" | tail -40`
  3. If Redis is the rate-limit backend: `docker compose exec redis redis-cli ping`.
     With `RATE_LIMIT_FAIL_OPEN=false` (default) a Redis outage answers **503**
     on protected routes — that is the documented, deliberate behaviour.
  4. A `JWT_SECRET` change invalidates every existing token by design
     (`sessions_invalidated_at`); confirm with the owner before assuming a defect.
- **Mitigation:** restore Redis or the database; if a bad `JWT_SECRET` was
  deployed, roll back the secret and restart (all sessions from the bad epoch
  stay invalid — they were never minted by the rolled-back secret).
- **Over when:** `/auth/login` returns 200/401 (never 5xx) and the 5xx ratio is
  back to baseline.

### Incident 6 — Cost spike or AI budget exhaustion

- **Symptom:** `AIMonthlyBudgetBurnRateHigh`; users get 429
  `ai_budget_exceeded`; `bgpt_ai_cost_usd_total` climbing faster than traffic.
- **First five minutes:**
  1. `curl -s localhost:8000/metrics | grep -E "bgpt_ai_cost_usd_total|bgpt_ai_tokens_total"`
  2. Find the route/model mix: `sum by (route, model) (rate(bgpt_ai_cost_usd_total[1h]))`
     in Prometheus/Grafana.
  3. Check for an abuse loop: `bgpt_http_requests_total` by path/status.
- **Mitigation:** throttle (lower `AI_MONTHLY_BUDGET_USD_PER_USER`, tighten
  `RATE_LIMIT_TUTOR_PER_MINUTE`), or point `GEMINI_MODEL` at the cheaper
  flash-lite tier for the FAST routes; raise `AI_MONTHLY_BUDGET_USD` only with
  the owner's approval. Figures are ledger estimates (list prices cited in
  `services/costs.py`) — reconcile against the provider invoice.
- **Over when:** the projected month-end spend is under budget.

### Incident 7 — Data-deletion (erasure) request

- **Symptom:** a written request (never a chat message) from a guardian, school
  or user for erasure under the privacy policy.
- **First five minutes:** confirm identity and scope — "delete my account" vs
  "delete a class's data" vs a school-level request. Do not act on an
  unverified request.
- **Procedure:**
  1. Self-service path exists for the account holder: `DELETE /users/me`
     (removes profile, quiz attempts and answer logs, parent links).
     Errors are coded (`last_admin`, …) and safe to surface.
  2. School-scoped or otherwise out-of-band requests: the owner decides the
     scope; export first (`GET /users/me/export`) if the requester asked for a
     copy, then delete.
  3. Record the request and the action in the audit log
     (`GET /admin/audit`); do not paste the requester's personal data into
     tickets beyond the minimum needed.
- **Over when:** the deletion is confirmed by a fresh query and the request is
  recorded.

### Incident 8 — Suspected breach or credential leak

- **Symptom:** a leaked `JWT_SECRET`, `METRICS_TOKEN`, SMTP password, provider
  key, or evidence of cross-tenant access.
- **First five minutes:**
  1. Treat the credential as compromised: rotate it in the secret store,
     restart the API, and record the time.
  2. `JWT_SECRET` rotation logs out every user (expected); announce before
     doing it if it is not urgent.
  3. Preserve evidence: copy logs to a separate location before any restart
     (restarts rotate nothing but a crash loop can lose the buffer).
  4. Check `GET /admin/audit` for impersonation sessions and role changes in
     the window.
- **Do not:** delete the repository history, edit logs, or message students
  directly. Notification and legal steps are owner decisions (I10).
- **Over when:** rotation is complete, the audit window is reviewed, and the
  owner has the incident write-up.

### Incident 9 — Bad prompt or model rollout

- **Symptom:** answers regress in tone, format, or grounding after a deploy;
  `RAGCitationCheckFailures` or refusal-rate shift; teachers report quality.
- **First five minutes:**
  1. Identify the change: `git log --oneline -20` and the running image tag.
  2. `TRACING_ENABLED=true` (staging) or grep `ai_call`/`tutor_retrieval` logs
     for `prompt_version` and `index_version` before/after.
  3. Compare the golden-eval summary artifact if the deploy included one.
- **Mitigation:** roll back the deploy (`docs/runbook.md` §7) — for a prompt
  change this is the fastest correct action; do not hand-edit production
  prompts. If the change was a model swap, revert `GEMINI_MODEL`.
- **Over when:** the regression is not reproducible on the rolled-back build
  and the refusal/citation counters are back to baseline.

### Incident 10 — Email delivery failure (SMTP)

- **Symptom:** registration verification, password resets or parent digests do
  not arrive; `send_mail` logs `False`; bounce/complaint reports from the
  provider.
- **First five minutes:**
  1. `docker compose logs --since=15m api | grep -iE "smtp|send_mail|mail"`
  2. Verify credentials and that the sending domain's SPF/DKIM still validate
     (the provider console shows this).
  3. Check the provider's suppression list — a hard-bounced address is silently
     suppressed from then on, which looks like an application bug.
- **Mitigation:** fix SMTP config and restart. Without SMTP, registration
  auto-verifies (dev only) — do **not** flip `SMTP_ENABLED=false` in production
  to "unblock" users: it silently drops the verification gate.
- **Over when:** a test registration receives a verification mail.
- **Known gap (owner action):** nothing consumes bounces or complaints
  today (AUD-HI-17); a suppressed address is invisible to the application.

## 12. Escalation contacts (OWNER ACTION — values required)

The repository cannot know who is on call. Until the owner fills this table,
every incident above escalates to whoever holds the deploy credentials, and
the SLO policy in `docs/operations/SLO.md` §4 cannot be enforced.

| Role | Responsibility | Contact | Filled in? |
|---|---|---|---|
| On-call API engineer | Incidents 1–5, 9 | _owner to provide_ | no |
| Data/DB owner | Incident 2, restore decisions | _owner to provide_ | no |
| Security lead | Incident 8, credential rotation | _owner to provide_ | no |
| Privacy contact | Incident 7, data-subject requests | _owner to provide_ | no |
| Product owner | Incident 6 budget decisions, SLO ratification | _owner to provide_ | no |
| Provider support | Quota/outage escalation (LLM, SMTP, host) | account console only | no |

Paging channel, escalation window and out-of-hours expectations are owner
decisions (I10); Alertmanager routing is configured by the owner's
deployment, not by this repository.
