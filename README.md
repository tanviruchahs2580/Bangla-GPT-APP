# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform.**

> **Status: PHASE 3 — QUIZZES & PROGRESS (verified).**
> FastAPI service: NCTB-style curriculum retrieval + grounded tutor Q&A +
> deterministic quiz engine + student profiles with chapter-level progress.
> Real LLM providers, real NCTB corpus, auth/RBAC, dashboards, mobile: pending.

## API surface (current)

| Endpoint | Purpose |
|---|---|
| `GET /health` `/live` `/ready` | Service health; readiness reports provider |
| `POST /tutor/ask` | Curriculum-grounded Q&A; refuses without evidence |
| `POST /students` · `GET /students/{id}` | Student profile |
| `POST /quizzes` | Generate MCQ quiz (answers never exposed) |
| `POST /quizzes/{id}/submit` | Server-side grading + review |
| `GET /students/{id}/progress` | Per-chapter accuracy + weak-chapter flags |

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
