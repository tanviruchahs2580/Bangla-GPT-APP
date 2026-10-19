# Environment Strategy (C-18)

How the four environments are configured, separated and promoted, and how the
`deploy/` and compose manifests are kept honest. Written for the audit item
C-18 ("configuration, data separation, promotion path; `deploy/` and compose
files agree with the documented topology. *Verify:* read deploy files;
`docker compose config`").

Machine-checked by `apps/api/tests/test_c2_env_strategy.py`: the compose file
must render (`docker compose config -q`), the profiles/services/documented
defaults below must match the render, and every environment name used here must
exist in `Settings`.

---

## 1. The four environments

| Environment | `ENV` value | Database | LLM | Rate-limit backend | Jobs | Where it runs |
|---|---|---|---|---|---|---|
| **development** | `development` (default) | SQLite file (`sqlite:///./bangla_gpt.db`) | `mock` | `memory` | `inline` | a developer machine; `uvicorn … --reload` or `docker compose --profile core` |
| **test** | `test` | in-memory SQLite (`sqlite://`), or PostgreSQL via `BGPT_TEST_DATABASE_URL` | `mock` | `memory` | not started (no lifespan) | CI and local pytest |
| **staging** | `staging` | PostgreSQL (own instance/volume) | real provider key | `redis` | `arq` worker | a compose project on a staging host; same images as prod |
| **production** | `production` | PostgreSQL 16 + pgBackRest volume | real provider key | `redis` | `arq` worker | `docker compose --profile core,worker,web,tls,postgres,monitoring,backup` behind Caddy |

`staging` is deliberately in `Settings.PRODUCTION_ENVS` (`config.py`), so the
strict boot guard, secret suppression and docs lock-down that apply to
production apply to staging too -- only the *data* is non-authoritative. That
parity is pinned by `apps/api/tests/test_env_parity.py`.

There is no environment-specific code branch anywhere in the application: every
difference above is a value in the one typed settings object
(`bangla_gpt_api/config.py`, a `pydantic-settings` `BaseSettings`), and
`enforce_production_safety(settings)` is the single fail-fast gate for the
values production must not guess (no default JWT secret, no in-memory database,
no mock provider without an explicit opt-in, PII encryption key present).

## 2. Configuration surface

| File | Purpose | Committed? |
|---|---|---|
| `.env.example` | documents **every** `Settings` field with its default and comment; enforced by `apps/api/tests/test_env_example.py` | yes |
| `.env.production.example` | the production-shaped superset (secrets left blank, Postgres/pgBackRest/Caddy values) | yes |
| `.env` | a developer's or a host's actual values | **no** (`.gitignore`: `.env`, `.env.*`, with only the two `*.example` files re-included) |
| compose `environment:` blocks | the container's allowlist of `${VAR:-default}` names | yes (`docker-compose.yml`) |

Rules:

1. A new setting is added to `config.py`, `.env.example` and, if production
   cares about it, `.env.production.example` **in the same change** -- the
   example-vs-settings test fails otherwise.
2. Secrets never enter git. CI runs gitleaks over the diff and the history; the
   only reviewed allowlist entry is the deliberately invalid benchmark fixture
   (`.gitleaks.toml`).
3. The compose file may only pass through variables the settings object reads.
   The rendered service must not need `.env` to be present: every name has an
   explicit default (`${VAR:-default}`), so `docker compose config -q` succeeds
   on a bare checkout.

## 3. Data separation

- **development** writes a local SQLite file, ignored by git; it is thrown away
  rather than migrated.
- **test** uses a per-test in-memory database by construction
  (`apps/api/tests/conftest.py` neutralises any real `.env` and forces
  `sqlite://`), so a test run cannot read or write a developer's data. The
  PostgreSQL job in CI sets `BGPT_TEST_DATABASE_URL` and truncates every table
  between tests, which is what keeps the same suite honest on the engine
  production uses.
- **staging** and **production** have separate PostgreSQL instances with
  separate volumes (`pg_data`) and separate pgBackRest repositories. No
  environment shares a database URL; the promotion path (below) never copies
  data between environments, only schema.
- Retention and erasure behave identically everywhere because they are jobs in
  the shared code path (`services/retention.py`), not environment switches.

## 4. Promotion path

```text
commit ─▶ CI (api 3.11+3.12, postgres, web, docker, e2e, guardrails, security)
       ─▶ images published to GHCR, tagged with the commit SHA  (API_TAG / WEB_TAG)
       ─▶ staging: docker compose pull && docker compose config -q
                   && docker compose run --rm api alembic upgrade head
                   && docker compose up -d --wait
       ─▶ acceptance probes (health, /status, one golden-set run)
       ─▶ production: the SAME images at the same SHA, migrations first, then
                      rolling restart; no rebuild between environments.
```

Properties the path relies on:

- **one artifact**: the images carry the code and the pinned dependency set;
  environments differ only by environment variables, so "it worked in staging"
  is evidence about production.
- **migrations are code**: `alembic/**` is the only schema authority and
  `alembic upgrade head` is the only promotion step. `tests/test_migrations_models.py`
  and `tests/test_migration_drift*.py` keep the models and the migration chain
  in step so a promotion cannot fail on drift discovered at deploy time.
- **rollback**: redeploy the previous SHA (`API_TAG=<previous>`), which is why
  migrations are expected to be backward compatible for one release.

The operational walkthrough (host provisioning, TLS, certificates, backups,
restore drill) lives in [`../../deploy/DEPLOYMENT.md`](../../deploy/DEPLOYMENT.md);
this document is the map, not a second copy of it.

## 5. Compose topology (what `docker compose config` must show)

`docker-compose.yml` is profile-gated so a laptop can run one piece at a time
and a host can run the whole stack:

| Profile | Services | Purpose |
|---|---|---|
| `core` | `api`, `redis` | the API plus the rate-limit/queue Redis |
| `worker` | `worker` | the ARQ worker that owns the schedule when `JOBS_BACKEND=arq` |
| `web` | `web` | the built web bundle served by nginx |
| `tls` | `caddy` | TLS termination and the only public listener |
| `postgres` | `postgres` | the database (own volume, own credentials) |
| `monitoring` | `prometheus`, `grafana` | scrape, alert rules, dashboards |
| `backup` | `backup`, `pgbackrest` | the nightly backup one-shot and the pgBackRest sidecar/repository |

Documented defaults the render must keep (checked by the test below):
`ENV=production`, `LLM_PROVIDER=mock`, `RATE_LIMIT_BACKEND=redis`,
`JOBS_BACKEND=inline`, the API bound to `${API_HOST_BIND:-127.0.0.1}`, and the
`api`/`postgres` healthchecks present. `redis` deliberately has no healthcheck:
it runs `--save ''` with a 64 MB cap, so readiness is the API's `/ready`
(which pings it) rather than a container probe.

Verification commands:

```bash
docker compose config -q                       # manifests render, no missing vars
docker compose --profile core --profile worker --profile web --profile tls \
  --profile postgres --profile monitoring --profile backup config --services
docker compose config --profiles               # the profile list above
```

`apps/api/tests/test_c2_env_strategy.py` runs the first and third of those (and
`config --services`) when a docker CLI is present, and fails if the render
disagrees with this document.
