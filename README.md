# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform.**

> **Status: PHASE 4 — AUTH & TEACHER ANALYTICS (verified).**
> JWT auth (PBKDF2 password hashing), role + ownership enforcement, quiz
> engine, student progress, and teacher class analytics.
> Real LLM providers, real NCTB corpus, admin roles, dashboards, mobile: pending.

## API surface (current)

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` `/live` `/ready` | — | Service health; readiness reports provider |
| `POST /auth/register` `/auth/login` | — | Account creation (student/teacher), token issue |
| `POST /tutor/ask` | — (migration pending) | Curriculum-grounded Q&A; refuses without evidence |
| `GET /students/{id}` · `GET /students/{id}/progress` | owner/teacher | Profile & chapter-level progress |
| `POST /quizzes` · `POST /quizzes/{id}/submit` | owner/teacher | Generate MCQ quiz (answers never exposed) / grade |
| `GET /teacher/students` | teacher | Roster with attempt/average stats |
| `GET /teacher/classes/{level}/analytics` | teacher | Chapter accuracy + weak-topic flags |

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
