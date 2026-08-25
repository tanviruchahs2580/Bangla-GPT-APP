# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform.**

> **Status: PHASE 8 — WEB DASHBOARD & PRODUCTION HARDENING (verified).**
> Full student-teacher-parent-admin role set, authenticated tutor endpoint,
> quiz/progress, teacher analytics, admin management, parent child-linkage,
> GDPR-style self-service account deletion (`DELETE /users/me`), Prometheus
> `/metrics`, rate limiting, body-size guard, Alembic migrations (2 revisions),
> a CI-verified container, and a React web dashboard wired to the live APIs.
> Real LLM providers and the real NCTB corpus remain pending external inputs.

## API surface (current)

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` `/live` `/ready` | — (`ready` checks DB) | Service health |
| `GET /metrics` | — | Prometheus metrics (request counts/latency) |
| `POST /auth/register` `/auth/login` | — | Accounts (all roles; admin via bootstrap), tokens |
| `GET /users/me` · `DELETE /users/me` | any | Own profile; GDPR-style self-service deletion |
| `POST /tutor/ask` | any | Curriculum-grounded Q&A; refuses without evidence |
| `GET /students/{id}` · `GET /students/{id}/progress` | owner/teacher/admin | Profile & chapter-level progress |
| `POST /quizzes` · `POST /quizzes/{id}/submit` | owner/teacher | Generate / grade quizzes (answers never exposed) |
| `GET /teacher/students` · `GET /teacher/classes/{level}/analytics` | teacher/admin | Roster & chapter accuracy/weak-topic flags |
| `GET /admin/users` · `PATCH /admin/users/{id}/role` | admin | User management (last-admin guard) |
| `GET /admin/analytics/overview` | admin | Platform totals (now includes `parents`) |
| `POST /parents/link` · `GET /parents/me/children` | parent | Link child; list linked children |
| `GET /parents/me/children/{id}/progress` | parent (linked) | Scoped child progress |

Full reference: [docs/API.md](docs/API.md). Operations: [docs/runbook.md](docs/runbook.md).

## Quick start

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn bangla_gpt_api.main:app --reload
# http://127.0.0.1:8000/health  /live  /ready  /docs
```

Web dashboard:

```powershell
cd apps/web
npm install
npm run dev      # http://localhost:5173 (proxies /api to :8000)
npm run build    # type-checked production build → dist/
```

Environment variables are documented in `.env.example`. Default
`LLM_PROVIDER=mock` requires no API key; unknown providers fail loudly.

## Repository layout

```text
BanglaGptApp/
├── apps/api/                                 # FastAPI service
├── apps/web/                                 # React dashboard (Vite + TS)
├── docs/architecture.md                      # verified decisions + pending items
├── docs/API.md                               # hand-written endpoint reference
├── docs/runbook.md                           # operations runbook
├── .github/workflows/repository-sanity.yml   # CI: repo-level sanity checks
├── .github/workflows/ci.yml                  # CI: lint/type/tests/audit/web/docker
├── LICENSE                                   # MIT
├── Dockerfile
├── .gitignore
└── README.md
```

## CI/CD status

| Pipeline | Stage | Status |
|---|---|---|
| `ci.yml` api job | install → ruff lint → format → mypy → pytest (3.11+3.12) → pip-audit → alembic cycle → smoke | ✅ active |
| `ci.yml` web job | Node 24 → npm ci → tsc + vite build | ✅ active |
| `ci.yml` docker job | build image → run → `/health` + `/ready` probes | ✅ active |
| `repository-sanity.yml` | structure / secret-file / YAML validation | ✅ active |

Full roadmap: [docs/architecture.md](docs/architecture.md).

## License

[MIT](LICENSE)

