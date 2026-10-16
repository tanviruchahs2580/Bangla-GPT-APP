# bangla-gpt-api

The API service for **Bangla GPT APP** — an NCTB-grounded AI tutor for
Bangladeshi school students, grades 1–12.

The product-level README, the operator quick start and the deployment guide
are at the [repository root](../../README.md) and in
[`deploy/DEPLOYMENT.md`](../../deploy/DEPLOYMENT.md). This file covers only
what is specific to this package.

## What it is

A FastAPI application, 116 paths / 134 operations, deployed as a single
container behind a TLS-terminating proxy. It is not served directly to the
internet: it holds personal data about children, so the reverse proxy is the
boundary and HSTS is the proxy's job.

## Layout

```
src/bangla_gpt_api/
  main.py            app factory only; boot concerns are in initialize/
  initialize/        settings, observability, middleware, lifespan, schedulers
  routers/           HTTP surface, one module per domain
  services/          business logic (tutor, quiz, safety, costs, reports)
  providers/         LLM adapters (Gemini, OpenAI-compatible, mock)
  retrieval/         indexing and ranking
  auth/              password hashing (Argon2id), TOTP, single-use tokens
  db/                SQLAlchemy models and session factory
  evaluation/        golden-set harness
```

The dependency direction is one-way: `routers → deps/common → services`. No
module outside `main` imports `main`.

## Running it locally

```bash
# From apps/api, with the locked dependency set
python -m pip install --require-hashes -r constraints.txt
python -m pip install --no-deps -e ".[dev]"

pytest
ruff check . && ruff format --check .
mypy src
```

`constraints.txt` carries a hash per artifact, so the project itself is
installed separately with `--no-deps` — a local directory has no single
artifact to hash. Keep that two-step shape.

## Things a contributor will trip over

- **The app boots with `ENV=test` and a mock provider**, which is why the test
  suite is fast. Production guards (`main.enforce_production_safety`) refuse
  the insecure configuration and name every problem at once.
- **`docs/API.md` documents 30 of 134 operations** and is not generated from
  the OpenAPI schema. It is a known gap, not a reliable reference; read
  `/docs` on a development instance.
- **Retries and the worker timeout are coupled.** The per-attempt LLM timeout
  is derived from `LLM_TIMEOUT_SECONDS` and `LLM_MAX_RETRIES` so the whole
  chain fits inside gunicorn's `--timeout 60`. Raising them together makes the
  app refuse to boot, rather than risk a SIGKILL that takes every concurrent
  request on the worker with it.
- **Foreign keys are not enforced by SQLite.** Every table that references a
  deleted account is cleaned explicitly in `DELETE /users/me`; PostgreSQL
  catches whatever that list misses. The CI Postgres job is the one that
  matters for this.

## Licence

MIT. Third-party notices, including the bundled Noto Sans Bengali font and its
OFL-1.1 licence, are in [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).
