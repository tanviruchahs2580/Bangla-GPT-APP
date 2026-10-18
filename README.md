# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform.**

Five roles (student, teacher, parent, school admin, platform admin), a grounded
multi-turn AI tutor with SSE streaming, quizzes and question papers with teacher
review flows, curriculum coverage and weakness analytics, classroom management,
school tenancy isolation, child-safety moderation, PWA + Android (Capacitor),
and bn/en i18n with dark mode.

**Current version: 0.9.2** (see `apps/api/pyproject.toml` / `apps/web/package.json`).

- **Live web app:** https://bangla-gpt-app.vercel.app
- **Production API origin (FE-01):** the Vercel frontend forwards `/api/*`
  through an edge proxy (`apps/web/api/[[...path]].ts`) to the origin set in
  the `API_ORIGIN` project environment variable — no tunnel URL is baked into
  the repo anymore. Until `API_ORIGIN` is set in the Vercel project settings,
  `/api/*` answers 503 `api_origin_unconfigured` by design. Point it at a
  stable origin (VM/PaaS + named tunnel or direct domain) —
  [docs/operations/PRODUCTION_DEPLOYMENT.md](docs/operations/PRODUCTION_DEPLOYMENT.md).

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
center, status page). For the whole surface use the checked-in inventory
[docs/route_baseline.md](docs/route_baseline.md) or the live `/openapi.json`
from a running instance. [docs/API.md](docs/API.md) is the hand-written
request/response reference for the 31 core/auth/users/tutor/quiz/teacher/
parent/admin operations it documents — useful detail, not the full surface.
Operations: [docs/runbook.md](docs/runbook.md).
Launch gates for the owner: [docs/LAUNCH_READINESS_CHECKLIST.md](docs/LAUNCH_READINESS_CHECKLIST.md).
RAG design: [docs/RAG_ARCHITECTURE.md](docs/RAG_ARCHITECTURE.md).
NCTB pipeline: [docs/NCTB_DATA_PIPELINE.md](docs/NCTB_DATA_PIPELINE.md).
Current QA record: [docs/qa/QA_REPORT_2026-10-17.md](docs/qa/QA_REPORT_2026-10-17.md)
(superseded records archived:
[docs/archive/qa-audit-2026-10-16.md](docs/archive/qa-audit-2026-10-16.md),
[docs/archive/qa-audit-2026-10-14.md](docs/archive/qa-audit-2026-10-14.md),
[docs/archive/qa-audit-2026-10-06.md](docs/archive/qa-audit-2026-10-06.md)).

## Quick start

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r constraints.txt
.venv\Scripts\python -m pip install --no-deps -e ".[dev]"
# optional: build + serve the real NCTB curriculum corpus
.venv\Scripts\python scripts\build_nctb_corpus.py --data-dir ..\..\data\nctb --subset ssc-science
$env:NCTB_CORPUS_DIR = "..\..\data\nctb"
.venv\Scripts\python -m uvicorn bangla_gpt_api.main:app --reload
# http://127.0.0.1:8000/health  /live  /ready  /docs
```

Web dashboard:

```powershell
cd apps/web
npm ci
npm run dev      # http://localhost:5173 (proxies /api to :8000)
npm run build    # type-checked production build → dist/
npx vitest run   # frontend test suite
```

### Linux / macOS

```bash
cd apps/api
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r constraints.txt
.venv/bin/pip install --no-deps -e ".[dev]"
# optional: build + serve the real NCTB curriculum corpus
.venv/bin/python scripts/build_nctb_corpus.py --data-dir ../../data/nctb --subset ssc-science
export NCTB_CORPUS_DIR="../../data/nctb"
.venv/bin/python -m uvicorn bangla_gpt_api.main:app --reload
# http://127.0.0.1:8000/health  /live  /ready  /docs
```

Web dashboard:

```bash
cd apps/web
npm ci
npm run dev      # http://localhost:5173 (proxies /api to :8000)
npm run build    # type-checked production build -> dist/
npm test         # frontend test suite
```

`constraints.txt` pins exact versions with hashes, so a commit always installs
the same dependency set. Regenerate it with `pip-compile` when you change
`pyproject.toml` - see [CONTRIBUTING.md](CONTRIBUTING.md).

### Docker

```bash
# The API image exactly as it ships in production:
docker build -t bangla-gpt-api:local .

# API + redis. That is ALL the "core" profile starts: no web, no postgres,
# no proxy. This caption used to read "Whole stack (API + web + postgres +
# redis + proxy)", which was false -- and the README is a docs-as-test, so a
# reader following it waited for containers that never started. The profiles
# that exist are: core (api, redis), web, postgres, tls (caddy), worker,
# monitoring (prometheus, grafana), backup. Add the ones you need, e.g.
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
with hash checking, so the same commit builds the same dependency set.

Backend checks (from `apps/api`): `ruff check .`, `ruff format --check .`,
`mypy src`, `pytest -q`.

Environment variables are documented in `.env.example`. Default
`LLM_PROVIDER=mock` requires no API key; unknown providers fail loudly.

## Repository layout

```text
├── apps/api/                      # FastAPI service (src/tests/scripts/eval)
├── apps/web/                      # React dashboard (Vite + TS) + Capacitor Android
├── docs/                          # living documentation (see docs/README.md)
│   └── archive/                   # superseded point-in-time reports (do not quote)
├── deploy/                        # caddy / postgres / prometheus / grafana configs
├── scripts/                       # ops & maintenance scripts
├── data/nctb/                     # corpus manifests + quality reports
├── .github/workflows/             # CI, eval gate, release, Vercel deploy
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## CI/CD

| Workflow | What it does | Trigger |
|---|---|---|
| `ci.yml` | api: ruff → format → mypy → pytest (3.11+3.12) → pip-audit → alembic cycle → smoke; postgres journey tests; golden-eval: golden retrieval + eval-v2 baseline gate + red-team gate; web: tsc + build + vitest; docker build + probes | push/PR to main |
| `eval-gate.yml` | golden retrieval benchmark w/ grounded-accuracy gate + eval-v2 regression vs committed baseline | push/PR to main, or manual |
| `codeql.yml` | CodeQL SAST (security-extended) over the API (python) and web (javascript-typescript); findings to the Security tab | push/PR to main, weekly |
| `release.yml` | CI-gated: tag → GHCR images → optional SSH deploy w/ health-gated rollback | tag `v*.*.*`, or manual |
| `vercel-deploy.yml` | production web deploy (CI-gated) | `workflow_run` on a green `API CI` for main, or manual |

This table is itself checkable: every row above was read off the workflow's own
`on:` block, and two rows used to disagree with it (`vercel-deploy.yml` was
listed as "push to main" when it runs on a `workflow_run`, and `eval-gate.yml`
as main-push-only when it also runs on pull requests). A trigger table that is
wrong is worse than absent, because it is what an operator consults before
concluding a pipeline is broken.

## Documentation conventions

- `docs/` holds **living documentation** (architecture, runbook, ops, ADRs).
  Point-in-time session/audit reports go to `docs/archive/` and are never
  quoted as current state.
- There is exactly **one current QA record**, under `docs/qa/`
  (`docs/qa/QA_REPORT_YYYY-MM-DD.md`); when the next one supersedes it, it
  moves to `docs/archive/`.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch, commit, CI and merge
conventions.
