# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform.**

> **Status: PHASE 1 — API SKELETON (verified).**
> A working FastAPI service (`apps/api`) with health/readiness endpoints and a
> provider-abstraction layer for future LLM/RAG integration. Application
> features (tutor chat, NCTB RAG, quizzes, dashboards, mobile) have NOT been
> built yet.

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
