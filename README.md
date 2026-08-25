# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform.**

> **Status: PHASE 7 — PARENT DASHBOARD (verified).**
> Full student-teacher-parent-admin role set, quiz/progress, teacher analytics,
> admin management, parent child-linkage with scoped progress, rate limiting,
> body-size guard, Alembic migrations (2 revisions), and a CI-verified container.
> Real LLM providers, real NCTB corpus, web/mobile UIs: pending.

## API surface (current)

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` `/live` `/ready` | — (`ready` checks DB) | Service health |
| `POST /auth/register` `/auth/login` | — | Accounts (all roles; admin via bootstrap), tokens |
| `POST /tutor/ask` | — (migration pending) | Curriculum-grounded Q&A; refuses without evidence |
| `GET /students/{id}` · `GET /students/{id}/progress` | owner/teacher/admin | Profile & chapter-level progress |
| `POST /quizzes` · `POST /quizzes/{id}/submit` | owner/teacher | Generate / grade quizzes (answers never exposed) |
| `GET /teacher/students` · `GET /teacher/classes/{level}/analytics` | teacher/admin | Roster & chapter accuracy/weak-topic flags |
| `GET /admin/users` · `PATCH /admin/users/{id}/role` | admin | User management (last-admin guard) |
| `GET /admin/analytics/overview` | admin | Platform totals (now includes `parents`) |
| `POST /parents/link` · `GET /parents/me/children` | parent | Link child; list linked children |
| `GET /parents/me/children/{id}/progress` | parent (linked) | Scoped child progress |

## Quick start

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn bangla_gpt_api:app --reload
# http://127.0.0.1:8000/health  /live  /ready  /docs
```

Environment variables are documented in `.env.example`. Default
`LLM_PROVIDER=mock` requires no API key; unknown providers fail loudly.

## Repository layout

```text
BanglaGptApp/
├── apps/api/                                 # FastAPI service (Phase 1)
├── docs/architecture.md                      # verified decisions + pending items
├── .github/workflows/repository-sanity.yml   # CI: repo-level sanity checks
├── .github/workflows/ci.yml                  # CI: lint + tests (Py 3.11 & 3.12)
├── .gitignore
└── README.md
```

## CI/CD status

| Pipeline | Stage | Status |
|---|---|---|
| `ci.yml` | install → ruff lint → ruff format → pytest (3.11+3.12) | ✅ active |
| `repository-sanity.yml` | structure / secret-file / YAML validation | ✅ active |
| type check (mypy) | pending — add with first real domain logic |
| security scan (pip-audit) | pending — gate after dependency set stabilizes |
| build/deploy stages | NOT APPLICABLE yet (no Docker/target) |

Full roadmap: [docs/architecture.md](docs/architecture.md).
