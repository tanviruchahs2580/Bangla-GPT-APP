# Bangla GPT APP

[![API CI](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/ci.yml)
[![Eval gate](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/eval-gate.yml/badge.svg?branch=main)](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/eval-gate.yml)
[![CodeQL](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/codeql.yml)
[![Release](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/release.yml)
[![Vercel deploy](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/vercel-deploy.yml/badge.svg?branch=main)](https://github.com/tanviruchahs2580/Bangla-GPT-APP/actions/workflows/vercel-deploy.yml)

**NCTB-grounded, Bangla-first AI personal tutor platform.**

Five roles (student, teacher, parent, school admin, platform admin), a grounded
multi-turn AI tutor with SSE streaming, quizzes and question papers with teacher
review flows, curriculum coverage and weakness analytics, classroom management,
school tenancy isolation, child-safety moderation, PWA + Android (Capacitor),
and bn/en i18n with dark mode.

**Current version: 0.9.2.** `apps/api/pyproject.toml` is the single source of
truth; `python scripts/check_version.py` (run by CI) asserts that the web
`package.json`, the lockfile, this README, the deployment guide and the
CHANGELOG all agree with it.

![Student AI tutor screen, Bangla UI](docs/uiux_renovation_evidence/after/student-tutor.png)

*The committed screenshot set (before/after waves, mobile widths) lives in
[docs/uiux_renovation_evidence/](docs/uiux_renovation_evidence/README.md) — it
is UI evidence, not product marketing.*

## Status

Checked 2026-10-19 against the repository and the live deployment:

- **Hosted web app:** <https://bangla-gpt-app.vercel.app> answers 200 (the
  static shell).
- **Hosted API:** the Vercel edge proxy (`apps/web/api/[[...path]].ts`)
  forwards `/api/*` to the origin named by the `API_ORIGIN` project variable.
  As of 2026-10-19 the variable is set but the origin did not answer —
  `/api/health` returns `api_origin_unreachable` — so the hosted app serves
  without a working API until that origin is restored. To exercise a working
  API today, use the local quick start below.
- **Local quick start:** timed end to end on a fresh clone of this branch —
  5 min 10 s from `git clone` to the first `GET /health` → 200, with every
  documented probe (`/live`, `/ready`, `/docs`, `/openapi.json`) answering.
  The timing log and the deviations found are in the audit evidence
  (`E-R2-j2-001`).
- **Model provider:** `LLM_PROVIDER=mock` by default, so the whole stack runs
  with no API key; `gemini` needs `GEMINI_API_KEY`.
- **Version 0.9.2** is the newest released tag; `main` carries unreleased work.

## Prerequisites

| Tool | Version | Why / where it is pinned |
| --- | --- | --- |
| Python | 3.12 (3.11 is also tested) | `.python-version`, `apps/api/pyproject.toml` (`requires-python >=3.11`); CI runs the API suite on both |
| Node.js | 24 (`>=24 <25`) | `.nvmrc`, `apps/web/package.json` `engines`; `.tool-versions` for asdf |
| npm | >=11 | `apps/web/package.json` `engines` |
| Git + a POSIX shell | any current version | The Linux/macOS block below runs in bash; on Windows use Git Bash for that block, or the PowerShell block as written |
| Docker | optional | Only for the container path; not used by the pip+npm quick start |
| PostgreSQL | 16, optional | The API defaults to SQLite (`sqlite:///./bangla_gpt.db`); Postgres is used by the CI Postgres job and the compose `postgres` profile |
| GNU make + Git Bash | optional | `make setup / dev / test / ci` wrap the commands below (see [CONTRIBUTING.md](CONTRIBUTING.md)); the quick start does not need make |

## Quick start

The path below is the one that was timed; on Windows run the PowerShell block
as written, on Linux/macOS run the bash block.

### API

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r constraints.txt
.venv\Scripts\python -m pip install --no-deps -e ".[dev]"
# Optional: build and serve the real NCTB corpus. This stage downloads the
# official NCTB PDFs into ../../data/nctb/raw (gitignored, needs network) and
# then rewrites three TRACKED provenance files
# (data/nctb/manifests/acquisition_manifest.jsonl, data/nctb/qa_report.json,
# data/nctb/quality_report.json) plus the untracked coverage_report.json.
# On a fresh clone the sources already listed in the tracked manifest have no
# raw PDFs, so they report "ERROR=raw file missing" and the command still
# exits 0 with a partial corpus - it does not fail the quick start. Review the
# diff before committing it. Student-facing redistribution of NCTB content
# needs rights-holder permission; for a corpus-less boot, skip this step.
.venv\Scripts\python scripts\build_nctb_corpus.py --data-dir ..\..\data\nctb --subset ssc-science
$env:NCTB_CORPUS_DIR = "..\..\data\nctb"
.venv\Scripts\python -m uvicorn bangla_gpt_api.main:app --reload
# http://127.0.0.1:8000/health  /live  /ready  /docs
```

Linux / macOS — same commands, POSIX paths:

```bash
cd apps/api
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r constraints.txt
.venv/bin/pip install --no-deps -e ".[dev]"
.venv/bin/python scripts/build_nctb_corpus.py --data-dir ../../data/nctb --subset ssc-science   # optional; see the note above
export NCTB_CORPUS_DIR="../../data/nctb"
.venv/bin/python -m uvicorn bangla_gpt_api.main:app --reload
# http://127.0.0.1:8000/health  /live  /ready  /docs
```

`constraints.txt` pins exact versions with hashes, so a commit always installs
the same dependency set. Regenerate it with `pip-compile` when you change
`pyproject.toml` — see [CONTRIBUTING.md](CONTRIBUTING.md).

### Web dashboard

```bash
cd apps/web
npm ci
npm run dev      # http://localhost:5173 (proxies /api/* to 127.0.0.1:8000)
npm run build    # type-checked production build → dist/
npm test         # vitest suite (npx vitest run is equivalent)
```

The dev proxy is part of the tested path: with the API running,
`http://localhost:5173/api/health` returns `{"status":"ok"}`.

### Docker

```bash
# The API image exactly as it ships in production:
docker build -t bangla-gpt-api:local .

# API + redis. That is ALL the "core" profile starts: no web, no postgres,
# no proxy. The profiles that exist are: core (api, redis), web, postgres,
# tls (caddy), worker, monitoring (prometheus, grafana), backup. Add the ones
# you need, e.g.
#   docker compose --profile core --profile web --profile postgres --profile tls up -d --wait
#
# ENV defaults to "production", and the app refuses to boot in production
# without a real JWT_SECRET and admin credentials - that gate is deliberate.
# For a local stack, run as test. The API is published to the host on
# 127.0.0.1:8000 by default (only a host-side tunnel needs that; Caddy reaches
# it as api:8000 over the Compose network). API_HOST_PORT moves the port and
# API_HOST_BIND widens the interface - 0.0.0.0 exposes the API to the network.
ENV=test docker compose --profile core up -d --wait
curl -fsS http://127.0.0.1:8000/health        # {"status":"ok"}

docker compose --profile core logs -f api
docker compose --profile core down
```

The image pins its base by digest and installs from `apps/api/constraints.txt`
with hash checking, so the same commit builds the same dependency set. CI's
"Docker build & container smoke" job builds this exact image, runs it with a
plain `docker run`, and probes `/health` and `/ready` on every push; the
compose command above is that image plus Redis.

## Testing

Everything below is what CI runs (see `.github/workflows/ci.yml`); run it
locally from the repository root unless a directory is given.

| Suite | Command | Notes |
| --- | --- | --- |
| API tests | `cd apps/api && pytest -q` | Full domain suite; on a fresh clone, run `alembic upgrade head` first so `alembic check` has a schema to compare against |
| API tests on Postgres | `cd apps/api && BGPT_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/bgpt_test pytest` | Same suite on the production engine (per-test truncation isolation); needs a running Postgres 16 — CI runs this in the "Postgres engine check" job |
| Web tests | `cd apps/web && npm test` | vitest, 262 tests / 69 files at the checked commit |
| API lint + types | `cd apps/api && ruff check . && ruff format --check . && mypy src` | CI runs the same three |
| Web build | `cd apps/web && npm run build` | `tsc && vite build`, type-check included |
| Migration drift | `cd apps/api && alembic upgrade head && alembic check` | `check` alone fails on a database that has no migrations applied |
| Docs and repo guards | `python scripts/check_links.py --anchors`, `npx --yes markdownlint-cli2@0.23.3 "**/*.md"`, `npx --yes cspell "**/*.md"` | Relative links, markdown lint, English spelling (Bangla wording is reviewed separately, see `docs/native-review-sheet.md`) |
| Everything static | `make ci-static` | The Makefile wraps the gates above (`make test` adds both suites); make is a convenience and not installed on every host — the individual commands always work |

## Configuration

`.env.example` documents every variable with its default and comments; the
important ones for a first run:

| Variable | Default | Effect |
| --- | --- | --- |
| `ENV` | `development` | `production` refuses to boot without real `JWT_SECRET`/admin credentials (deliberate) |
| `LLM_PROVIDER` | `mock` | `mock` needs no key and never calls out; `gemini` needs `GEMINI_API_KEY`; unknown values fail loudly |
| `GEMINI_API_KEY` | empty | Required only for `gemini` |
| `DATABASE_URL` | `sqlite:///./bangla_gpt.db` | Point it at Postgres in real deployments |
| `JWT_SECRET` | empty | Required in production; generate with `openssl rand -hex 32` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | `admin@example.com` / empty | First admin; production requires a >=12-char password and rotation |
| `NCTB_CORPUS_DIR` | empty | Directory of the built corpus; empty means no NCTB retrieval |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | CORS allowlist for the dashboard |
| `SMTP_ENABLED` | `false` | With SMTP off, email verification is not gated |
| `METRICS_REQUIRE_AUTH` / `METRICS_TOKEN` | `false` / empty | In production both must be set or the app refuses to start |
| `REDIS_URL` / `RATE_LIMIT_BACKEND` | empty / `memory` | Shared rate-limit state across replicas |
| `LOG_LEVEL` / `SENTRY_DSN` | `INFO` / empty | Logging and error reporting |
| `CHAT_RETENTION_DAYS` | `180` | Retention window the purge job enforces |

The code–docs parity of this file is covered by `apps/api/tests/test_env_parity.py`
and `test_env_example.py`, which fail when `Settings` and `.env.example` drift.

## API surface (current)

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` `/live` `/ready` | — (`ready` checks DB) | Service health |
| `GET /metrics` | env-dependent (see note) | Prometheus metrics |
| `POST /auth/register` `/auth/login` | — | Accounts; tokens (`email_unverified` code when SMTP on) |
| `POST /auth/forgot` `/auth/reset` | — | Password reset (single-use hashed tokens) |
| `POST /auth/verify-email` `/auth/resend-verification` | mixed | Email verification flow |
| `GET /users/me` · `DELETE /users/me` · `GET /users/me/export` | any | Profile; GDPR delete/export |
| `POST /tutor/ask` | any | Grounded Q&A; safety screen; coverage-gated refusal |
| `POST /tutor/conversations` · `GET /tutor/conversations` | student | Multi-turn chat sessions |
| `GET /tutor/conversations/{id}/messages` | owner | Chat history |
| `POST .../messages` · `POST .../messages/stream` | owner | Chat turn (JSON or SSE tokens+done) |
| `POST /feedback` · `POST /events` | any | Answer ratings; privacy-safe analytics events |
| `GET /students/{id}` · `GET /students/{id}/progress` | owner/teacher/admin | Profile & progress |
| `POST /quizzes` · `POST /quizzes/{id}/submit` | owner/teacher | Quizzes (`requested`, `partial_quiz` note) |
| `POST /students/me/invite-code` | student | Single-use parent invite code |
| `GET /teacher/students` · `GET /teacher/classes/{level}/analytics` | teacher/admin | Roster & analytics |
| `GET /admin/users?q&role&limit&offset` · `PATCH /admin/users/{id}/role` | admin | Paginated user management |
| `GET /admin/analytics/overview` | admin | Platform totals |
| `POST /admin/maintenance/purge` | admin | Retention sweep (chats/tokens/invites) |
| `POST /parents/link` · `POST /parents/link/invite` · `GET /parents/me/children...` | parent | Linking (legacy ID + invite-code flows) |

¹ `/metrics` is unauthenticated only outside production. In production the
app refuses to start unless `METRICS_REQUIRE_AUTH=true` and `METRICS_TOKEN` is
set, and `/metrics` then requires `Authorization: Bearer $METRICS_TOKEN`
(`main.py::_validate_metrics`). A developer running `uvicorn` locally sees the
open endpoint; that is not what a deployed instance does.

This table covers the core surface only — the app registers 135 operations
(134 OpenAPI operations over 116 unique path templates; short tests, bulk
assignments, question papers, schools, notifications, KG re-teach, admin
center, status page). `apps/api/scripts/check_readme_contract.py` (run in CI)
asserts the counts in this section against the running app's OpenAPI schema, so
a stale number fails the build. For the whole surface use the checked-in
inventory [docs/route_baseline.md](docs/route_baseline.md) or the live
`/openapi.json` from a running instance. [docs/API.md](docs/API.md) is the
generated request/response reference.

## Repository layout

```text
├── apps/api/                      # FastAPI service (src/tests/scripts/eval)
├── apps/web/                      # React dashboard (Vite + TS) + Capacitor Android
├── docs/                          # living documentation — start at docs/README.md,
│   │                              # full tracked inventory at docs/INDEX.md
│   └── archive/                   # superseded point-in-time reports (do not quote)
├── deploy/                        # caddy / postgres / prometheus / grafana configs
├── scripts/                       # ops & maintenance scripts (+ doc guards)
├── data/nctb/                     # corpus manifests + quality reports
├── .github/workflows/             # CI, eval gate, release, Vercel deploy, scans
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Documentation

| Start here | What it is |
| --- | --- |
| [docs/README.md](docs/README.md) | Curated documentation index |
| [docs/INDEX.md](docs/INDEX.md) | Every tracked document, one line each (the map of `docs/`) |
| [docs/architecture.md](docs/architecture.md) | Architecture overview and decisions |
| [docs/RAG_ARCHITECTURE.md](docs/RAG_ARCHITECTURE.md) | Retrieval + grounding design with the measured baseline |
| [docs/runbook.md](docs/runbook.md) | Operations: deploy, roll back, diagnose |
| [docs/ai-system-card.md](docs/ai-system-card.md) | Intended use, limitations, measured evaluation results |
| [docs/threat-model.md](docs/threat-model.md) | STRIDE + OWASP LLM Top 10 + child-data LINDDUN-lite |
| [docs/LAUNCH_READINESS_CHECKLIST.md](docs/LAUNCH_READINESS_CHECKLIST.md) | Owner launch gates |
| [docs/operations/PRODUCTION_DEPLOYMENT.md](docs/operations/PRODUCTION_DEPLOYMENT.md) | Deployment architecture and procedure |

A guide that tells an operator to run a path that does not exist costs real
time during an incident, so `apps/api/scripts/check_doc_paths.py` (CI) fails
when a document names a repository path that is missing, and
`scripts/check_links.py` checks every relative link and `#anchor`.

## CI/CD

| Workflow | What it does | Trigger |
|---|---|---|
| `ci.yml` | api: ruff → format → mypy → pytest (3.11+3.12) → pip-audit → alembic cycle → smoke; postgres: alembic cycle + drift + smoke/race + **full domain suite on Postgres**; golden-eval: golden retrieval + eval-v2 baseline gate + red-team gate; web: tsc + build + vitest; docker build + probes; doc guards (paths, README contract, changelog, version, markdownlint) | push/PR to main; weekly `schedule` runs only the DAST baseline job |
| `eval-gate.yml` | golden retrieval benchmark w/ grounded-accuracy gate + eval-v2 regression vs committed baseline | push/PR to main, or manual |
| `codeql.yml` | CodeQL SAST (security-extended) over the API (python) and web (javascript-typescript); findings to the Security tab | push/PR to main, weekly |
| `release.yml` | CI-gated: tag → GHCR images → optional SSH deploy w/ health-gated rollback | tag `v*.*.*`, or manual |
| `vercel-deploy.yml` | production web deploy (CI-gated) | `workflow_run` on a green `API CI` for main, or manual |

Every row was read off the workflow's own `on:` block; the badges at the top of
this file show the same workflows' state on `main`.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) states the branch, commit, review and merge
rules, the definition of done, and how to keep the audit trail
(findings ids, evidence, risk/rollback) in the pull request. Small, reviewed
pull requests; `main` is the only long-lived branch.

## Support

[SUPPORT.md](SUPPORT.md) — where to ask for help, what support covers, and what
it does not.

Security problems have their own private channel: [SECURITY.md](SECURITY.md)
(never a public issue — this project holds children's data).

## License

[MIT](LICENSE)

Bundled third-party material keeps its own licence — see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Changelog

[CHANGELOG.md](CHANGELOG.md) records what changed in each release. It is
generated from the git history, so it cannot claim a release that did not
happen:

```bash
python apps/api/scripts/gen_changelog.py    # regenerate after landing work
```

CI fails if a commit is missing from it or a version has no matching tag.
