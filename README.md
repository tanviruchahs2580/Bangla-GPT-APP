# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform.**

> **Status: PHASE 6 — OBSERVABILITY + MIGRATIONS + EVAL HARNESS (verified).**
> Request IDs on every response, structured logging, DB-aware readiness,
> Alembic initial migration (upgrade/downgrade cycle verified), and a
> grounding-evaluation harness over a curated sample question set.
> Real LLM providers, real NCTB corpus, dashboards, mobile: pending.

## API surface (current)

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` `/live` `/ready` | — (`ready` now checks DB) | Service health; readiness includes DB |
| `POST /auth/register` `/auth/login` | — | Accounts (student/teacher; admin via bootstrap), tokens |
| `POST /tutor/ask` | — (migration pending) | Curriculum-grounded Q&A; refuses without evidence |
| `GET /students/{id}` · `GET /students/{id}/progress` | owner/teacher/admin | Profile & chapter-level progress |
| `POST /quizzes` · `POST /quizzes/{id}/submit` | owner/teacher | Generate MCQ quiz (answers never exposed) / grade |
| `GET /teacher/students` | teacher/admin | Roster with attempt/average stats |
| `GET /teacher/classes/{level}/analytics` | teacher/admin | Chapter accuracy + weak-topic flags |
| `GET /admin/users` · `PATCH /admin/users/{id}/role` | admin | User management (last-admin guard) |
| `GET /admin/analytics/overview` | admin | Platform totals |

Every response now carries `X-Request-ID`. Hardening: per-IP sliding-window rate limits, body-size cap.

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
