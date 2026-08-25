# Architecture — Bangla GPT APP

> Status: Phase 1 (API skeleton). This document records **actual, verified**
> decisions only. Pending items are explicitly marked.

## Goal

NCTB-grounded, Bangla-first AI personal tutor platform for Bangladesh:
students get a safe curriculum-aligned tutor; teachers get an AI assistant;
parents/admins get oversight. Full requirement baseline lives in the project
master plan (REQ-001..REQ-035+).

## Verified environment constraints (2026-08-25)

| Toolchain | Present | Decision |
|---|---|---|
| Python 3.12.10 | ✅ | Backend language |
| Node 24 / npm 11 | ✅ | Reserved for web dashboard phase |
| Docker | ❌ | Containerization deferred |
| Flutter SDK | ❌ | Mobile deferred (cannot verify locally) |
| LLM API keys | ❌ not provided | Provider abstraction + deterministic mock |

## Stack decisions (Phase 1)

- **Backend:** Python 3.11+/FastAPI, pydantic-settings. Rationale: dominant
  ecosystem for RAG/LLM tooling; verifiable on this machine.
- **Layout:** monorepo. `apps/api` first; `apps/web`, `apps/mobile` reserved.
- **Config:** env-driven (`Settings`), `.env.example` documents variables;
  real `.env` is gitignored.
- **LLM access:** `LLMProvider` protocol + factory. `mock` is the default and
  is fully tested. Real providers (e.g., Gemini/OpenAI) are added ONLY when a
  key is supplied by the user; unknown values fail loudly (`503` on `/ready`).
- **Testing:** pytest + FastAPI TestClient; CI runs the suite on Python
  3.11 and 3.12.

## Repository layout

```text
BanglaGptApp/
├── apps/api/                 # FastAPI service (Phase 1)
│   ├── src/bangla_gpt_api/
│   │   ├── config.py         # Settings (env-driven)
│   │   ├── main.py           # app factory: /health /live /ready
│   │   └── providers/        # LLMProvider protocol, mock impl, factory
│   └── tests/
├── .github/workflows/        # repository-sanity.yml, ci.yml
└── docs/architecture.md
```

## Pending (explicitly NOT built yet)

| Item | Blocker |
|---|---|
| Real LLM provider integration | API key required from user |
| NCTB ingestion/RAG pipeline | Textbook corpus required |
| Vector store | Chosen together with corpus scale; no Docker locally |
| Web dashboard | Phase after API endpoints stabilize |
| Mobile (Flutter) | SDK not installed on dev machine |
| Voice, offline sync, load testing, deployment | Depend on above |
