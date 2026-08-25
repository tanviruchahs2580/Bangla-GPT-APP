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

## Stack decisions (Phase 2 — student domain core, verified)

- **Curriculum model** (`curriculum/models.py`): `CurriculumMeta` carries the
  full provenance set required by the master plan (`curriculum_year`,
  `class_level`, `subject`, `book`, `chapter`, `section`, `page`, `language`,
  `source`, `version`, `content_type`). Every retrieval chunk keeps its
  metadata; versions never mix because filters key on them.
- **Ingestion** (`ingestion/text_ingester.py`): deterministic marker-based
  ingester for structured plain text (chapter/section/paragraph). PDF/OCR
  adapters pending corpus arrival.
- **Retrieval** (`retrieval/bm25.py`): dependency-free Okapi BM25 with
  curriculum-aware filtering. A Bangla-block tokenizer (U+0980-U+09FF) is
  required — `\w+` splits on Bangla vowel signs/virama and destroys words
  (verified bug, fixed, regression-tested).
- **Tutor service** (`services/tutor.py`): retrieve → grounding gate →
  provider generate → cited answer. Below-threshold retrieval returns an
  explicit insufficient-evidence refusal instead of inventing content
  (hallucination guard, master §32).
- **Sample corpus** (`data/sample_nctb/`): ORIGINAL synthetic Bangla text for
  pipeline verification only — NOT real NCTB content.

## Verified behaviors (Phase 2)

- `/tutor/ask` grounded path returns cited sources (book/chapter/section).
- Out-of-curriculum questions refuse with `grounded=false`.
- Payload validation (question length, class range) returns 422.
- Unconfigured providers: `/ready` and `/tutor/ask` return 503 loudly.

## Stack decisions (Phase 3 — quizzes & progress, verified)

- **Persistence** (`db/`): SQLAlchemy 2.0 (`students`, `quiz_attempts`,
  `answer_log`). SQLite default (in-memory for tests; file URL via
  `DATABASE_URL`). `create_all` startup is dev-grade — Alembic migrations
  pending before any shared environment.
- **Quiz engine** (`services/quiz.py`): deterministic cloze generator over
  curriculum chunks (rare-term blanking, seeded distractor sampling). This is
  an honest baseline — an LLM-backed generator with a validation gate replaces
  it later; generated questions are never marked trusted without validation.
- **Answer safety**: quiz payloads never contain answer keys; grading happens
  server-side; double-submit and length-mismatch rejected.
- **Progress** (`/students/{id}/progress`): per-chapter accuracy computed from
  answer logs; chapters under 60% flagged as weak.
- **DI style**: FastAPI `Annotated` dependencies; ruff B008 kept enabled.

## Verified behaviors (Phase 3)

- Deterministic generation (same seed ⇒ same quiz), valid 4-option MCQs.
- No answer leakage in `/quizzes` response (asserted on raw JSON).
- Grading integrity: review rows reconcile exactly with stored score.
- Student validation, unknown student/attempt → 404/422 paths.

## Pending (explicitly NOT built yet)

| Item | Blocker |
|---|---|
| Real LLM provider integration | API key required from user |
| NCTB ingestion/RAG pipeline | Textbook corpus required |
| Vector store | Chosen together with corpus scale; no Docker locally |
| Web dashboard | Phase after API endpoints stabilize |
| Mobile (Flutter) | SDK not installed on dev machine |
| Voice, offline sync, load testing, deployment | Depend on above |
