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
| `GET /metrics` | — | Prometheus metrics |
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

This table covers the core surface only — the API now exposes ~135 routes
(short tests, bulk assignments, question papers, schools, notifications, KG
re-teach, admin center, status page). Generated baseline:
[docs/route_baseline.md](docs/route_baseline.md).
Full reference: [docs/API.md](docs/API.md). Operations: [docs/runbook.md](docs/runbook.md).
Launch gates for the owner: [docs/LAUNCH_READINESS_CHECKLIST.md](docs/LAUNCH_READINESS_CHECKLIST.md).
RAG design: [docs/RAG_ARCHITECTURE.md](docs/RAG_ARCHITECTURE.md).
NCTB pipeline: [docs/NCTB_DATA_PIPELINE.md](docs/NCTB_DATA_PIPELINE.md).
Current QA record: [docs/qa-audit-2026-10-06.md](docs/qa-audit-2026-10-06.md).

## Quick start

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
# optional: build + serve the real NCTB curriculum corpus
.venv\Scripts\python scripts\build_nctb_corpus.py --data-dir ..\..\data\nctb --subset ssc-science
$env:NCTB_CORPUS_DIR = "..\..\data\nctb"
.venv\Scripts\python -m uvicorn bangla_gpt_api.main:app --reload
# http://127.0.0.1:8000/health  /live  /ready  /docs
```

Web dashboard:

```powershell
cd apps/web
npm install
npm run dev      # http://localhost:5173 (proxies /api to :8000)
npm run build    # type-checked production build → dist/
npx vitest run   # frontend test suite
```

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
| `ci.yml` | api: ruff → format → mypy → pytest (3.11+3.12) → pip-audit → alembic cycle → smoke; postgres journey tests; golden-eval gate; web: tsc + build + vitest; docker build + probes | push/PR to main |
| `eval-gate.yml` | golden retrieval benchmark w/ grounded-accuracy gate | push to main |
| `release.yml` | tag → GHCR images → optional SSH deploy w/ health-gated rollback | tag `v*` |
| `vercel-deploy.yml` | production web deploy (CI-gated) | push to main |

## Documentation conventions

- `docs/` holds **living documentation** (architecture, runbook, ops, ADRs).
  Point-in-time session/audit reports go to `docs/archive/` and are never
  quoted as current state.
- There is exactly **one current QA record** (`docs/qa-audit-YYYY-MM-DD.md`);
  it moves to `docs/archive/` when the next one supersedes it.

## License

[MIT](LICENSE)
