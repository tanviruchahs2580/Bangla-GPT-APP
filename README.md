# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform.**

Five roles (student, teacher, parent, school admin, platform admin), a grounded
multi-turn AI tutor with SSE streaming, quizzes and question papers with teacher
review flows, curriculum coverage and weakness analytics, classroom management,
school tenancy isolation, child-safety moderation, PWA + Android (Capacitor),
and bn/en i18n with dark mode.

**Current version: 0.9.3.** The single source of truth is
`apps/api/pyproject.toml` (`[project] version`), mirrored by
`apps/web/package.json`; release tags, the GHCR image tags and this line follow
it. Nothing else may carry a version number.

- **Live web app:** <https://bangla-gpt-app.vercel.app>
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
| `POST /auth/register` `/auth/login` `/auth/logout` | — (`logout` any) | Accounts; tokens (`email_unverified` code when SMTP on); `logout` revokes the presented token's jti (fail-closed store) |
| `POST /auth/forgot` `/auth/reset` | — | Password reset (single-use hashed tokens) |
| `POST /auth/verify-email` `/auth/resend-verification` | mixed | Email verification flow |
| `POST /auth/renew` | any authenticated | Session slide: fresh jti + full window while the presented token still verifies (expired and impersonated tokens refused; the web client renews proactively so a class session survives past minute 60) |
| `GET /users/me` · `DELETE /users/me` (body: current `password`, F-142) · `GET /users/me/export` · `POST /users/me/sessions/revoke` | any | Profile; re-authed GDPR delete/export; revoke every session (epoch stamp) |
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

This table covers the core surface only — short tests, bulk assignments,
question papers, schools, notifications, KG re-teach, admin center and the
status page are not listed here. The full surface is the served schema at
`/openapi.json` (the author for tooling and tests); the checked-in
[docs/route_baseline.md](docs/route_baseline.md) is a dated inventory snapshot
and can lag it. [docs/API.md](docs/API.md) is the hand-written
request/response reference for the core/auth/users/tutor/quiz/teacher/parent/
admin operations it documents, including the SSE stream and the paginated
endpoints — useful detail, not the full surface. No operation counts are
repeated here on purpose: they go stale with every route change, and the
schema is one request away.
Operations: [docs/runbook.md](docs/runbook.md).
Launch gates for the owner: [docs/LAUNCH_READINESS_CHECKLIST.md](docs/LAUNCH_READINESS_CHECKLIST.md).
RAG design: [docs/RAG_ARCHITECTURE.md](docs/RAG_ARCHITECTURE.md).
NCTB pipeline: [docs/NCTB_DATA_PIPELINE.md](docs/NCTB_DATA_PIPELINE.md).
Current QA record: [docs/qa/QA_REPORT_2026-10-30.md](docs/qa/QA_REPORT_2026-10-30.md)
(superseded records archived:
[docs/archive/QA_REPORT_2026-10-29.md](docs/archive/QA_REPORT_2026-10-29.md),
[docs/archive/QA_REPORT_2026-10-27.md](docs/archive/QA_REPORT_2026-10-27.md),
[docs/archive/QA_REPORT_2026-10-17.md](docs/archive/QA_REPORT_2026-10-17.md),
[docs/archive/qa-audit-2026-10-16.md](docs/archive/qa-audit-2026-10-16.md),
[docs/archive/qa-audit-2026-10-14.md](docs/archive/qa-audit-2026-10-14.md)).

## Quick start

Prerequisites:

- **Python 3.11 or newer** (`requires-python = ">=3.11"` in
  `apps/api/pyproject.toml`; CI runs 3.11 and 3.12).
- **Node 24 with npm 11** (`engines` in `apps/web/package.json`; `.nvmrc`
  pins 24 for nvm users).
- **Docker**, only for the Docker section below.

CI runs both install two-steps: the Linux form in the `Lint & test` job, the
PowerShell form (venv, install, dev server, web build) in the `Quick start
(Windows PowerShell)` job.

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
# without a real JWT_SECRET, admin credentials, PII_ENC_KEY and the
# METRICS_REQUIRE_AUTH/METRICS_TOKEN pair - that gate is deliberate.
# For a local stack, run as test. A production run needs the full key list
# from deploy/DEPLOYMENT.md section 6 in .env; compose forwards every one of
# them, so no compose edit is needed. The API is published to the host on
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

All nine workflows under `.github/workflows/`, with the job ids each one runs:

| Workflow | What it does (job ids) | Trigger |
|---|---|---|
| `ci.yml` | `api` — ruff check → ruff format → mypy → pytest on 3.11 and 3.12 (coverage gate) → pip-audit → alembic up/down/up → import smoke → OpenAPI-fixture diff; `quickstart-windows` — the README's PowerShell quick start (venv → hash-locked install → dev server `/health` → `npm ci` + build) on `windows-latest`; `postgres` — migration cycle + `alembic check` drift + journey/race tests + the **full domain suite on Postgres**; `sbom` — CycloneDX manifests for python and web; `web` — npm audit → vitest coverage → eslint → prettier → tsc+vite build; `guardrails` — the repo-contract checks below, including the readme/workflow-table guard; `e2e` — Playwright chromium against the real app plus the offline shell; `e2e-engines` — the Bangla shaping/`Intl` specs on firefox and webkit as well (pull requests only); `docker` — image build → Trivy gate → `/health`+`/ready` probes → k6 smoke | push to `main`, pull_request to `main`, workflow_dispatch |
| `eval-gate.yml` | `eval-gate` — golden v2 suite vs the committed baseline (>2pp regression fails), the 24-question golden retrieval gate (`apps/api/scripts/evaluate_golden.py`) and the red-team moderation gate (`evaluation.cli --redteam`); optional non-blocking real-model probe on manual dispatch | push/pull_request to `main`, workflow_dispatch |
| `codeql.yml` | `analyze` — CodeQL SAST (security-extended) over python and javascript-typescript; SARIF lands in the Security tab | push/pull_request to `main`, schedule weekly |
| `release.yml` | `ci-gate` — fails when green CI for the commit is missing and when the tag != the package version; `build-push` — GHCR images tagged with both the release tag and the commit sha, with SBOM + provenance; `scan-images` — Trivy + attestation verification of the pushed digests; `deploy` — SSH deploy with health-gated rollback (only when `DEPLOY_ENABLED=true`) | push tags `v*.*.*`, workflow_dispatch |
| `vercel-deploy.yml` | `deploy` — production web deploy after a green `API CI` on the same sha, with a post-deploy `/api/health` smoke | workflow_run on a completed `API CI` for `main`, workflow_dispatch |
| `android-release.yml` | `bundle` — release-signed AAB + APK artifacts (never uploads to Play by itself); `debug-assemble` — proves the Android shell assembles from the current web bundle | workflow_dispatch, push tags `v*`, pull_request touching `apps/web/**` |
| `uptime.yml` | `probe` — public `/api/health` (plus the optional origin probe); `page` — files a deduplicated issue when the probe fails; `resolve` — closes it on the next green probe | schedule every 15 min, workflow_dispatch |
| `scorecard.yml` | `analysis` — OpenSSF Scorecard; SARIF into the Security tab | branch_protection_rule, schedule weekly, push to `main`, workflow_dispatch |
| `secret-masking.yml` | `echo-dummy` + `verify-masking` — echoes a throwaway secret and asserts the job log never contains it | workflow_dispatch only |

This table is checked by the `guardrails` job in `ci.yml`
(`README and docs/ci.md agree with the workflows`): every workflow file must
have a row here, the row must name every job id in the file, and the trigger
cell must name exactly the event keys in that workflow's own `on:` block. The
guard exists because the previous table was wrong in all three ways — it
invented a `golden-eval` job inside `ci.yml`, dropped the `sbom` and
`guardrails` jobs, and four of the nine workflows were absent entirely.

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
