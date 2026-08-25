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

## Stack decisions (Phase 4 — auth & teacher analytics, verified)

- **Credentials**: PBKDF2-HMAC-SHA256 (200k iterations, per-user salt,
  constant-time compare) via stdlib — no hashing dependency.
- **Tokens**: HS256 JWT (`pyjwt`), `sub`=user id, `role`, `exp`
  (`JWT_EXPIRE_MINUTES`). Secret from env (`JWT_SECRET`); the committed dev
  default is documented as insecure-on-purpose in `.env.example`.
- **Authorization**: role gates (`student`, `teacher`; admin roles pending) +
  object-level ownership checks — students can only read/submit their own
  data; teachers have class-wide read access and may generate quizzes for
  students. Cross-student access returns 403 (regression-tested).
- **Teacher API**: roster with per-student attempt/average stats; class-level
  chapter analytics with weak-chapter (<60% accuracy) identification.
- Legacy unauthenticated `POST /students` was removed; profiles are now
  created through `/auth/register` only.

## Verified behaviors (Phase 4)

- Register/login round-trips; duplicate email → 409; bad email/short
  password/missing class_level → 422; wrong credentials → generic 401
  (no user enumeration).
- Missing/garbage/forged-secret/expired tokens all rejected with 401;
  student token on teacher endpoints → 403.
- Cross-student isolation enforced on profile, progress, quiz start/submit.

## Stack decisions (Phase 5 — RBAC completion & hardening & container, verified)

- **Admin role**: never self-registered (`/auth/register` Literal rejects it).
  Bootstrap admin is created at startup only when `ADMIN_EMAIL` +
  `ADMIN_PASSWORD` are set and no admin exists. Admin endpoints: list users,
  change roles (with last-admin demotion guard → 409), platform overview
  counts.
- **Rate limiting** (`RateLimitMiddleware`): in-memory sliding window per
  client IP on `/auth/login` and `/tutor/ask`; limits via settings; returns
  429. Known limits: per-process only (multi-worker deployments need Redis or
  equivalent) — documented, pending until infra exists.
- **Body-size guard**: requests with `Content-Length` above `MAX_BODY_BYTES`
  (default 64 KiB) rejected 413 before routing.
- **Container** (`Dockerfile`): python:3.12-slim, non-root user, healthcheck,
  package install from source. Verified by CI job that builds the image,
  boots it, and asserts `/health` + `/ready` over HTTP.

## Stack decisions (Phase 6 — observability, migrations, evaluation harness, verified)

- **Logging**: `logging_config` (JSON lines via stdlib) + `RequestIdMiddleware`
  that echoes/creates `X-Request-ID` on every response. The `ready` probe now
  checks database reachability in addition to the LLM provider.
- **Migrations**: Alembic (initial revision `7a826704cc96`) checked in;
  `upgrade head → downgrade base → upgrade head` verified locally and in CI.
  Runtime still calls `create_all` for the in-memory test databases —
  Alembic is authoritative for any file/persistent database.
- **Evaluation harness**: `evaluation/runner.py` (`EvalQuestion` /
  `evaluate_questions`) scores grounding correctness over a curated JSON set
  (`eval/sample_questions.json`, 10 items: 5 in-domain true, 5 out true →
  hallucination-guard). The sample file proves 100% accuracy on the current
  mock tutor; a real LLM key swaps in without changing the harness.

## Stack decisions (Phase 7 — parent dashboard, verified)

- **Parent linkage**: `parents` + `parent_student_links` (unique per pair)
  tables; `/parents/link` (parent role), `/parents/me/children` and
  `/parents/me/children/{id}/progress` scoped by explicit link. Tests assert
  linkage, duplicate 409, unknown 404, and cross-parent isolation (403
  vs 404 as appropriate).
- **Role set** now `student | teacher | parent | admin`; registration
  enforces `class_level` only for students; `RoleUpdateRequest` covers all
  four. `AdminOverview` now reports `parents` count.

## Pending (explicitly NOT built yet)

| Item | Blocker |
|---|---|
| Real LLM provider integration | API key required from user |
| NCTB ingestion/RAG pipeline | Textbook corpus required |
| Vector store | Chosen together with corpus scale; no Docker locally |
| Web dashboard | Phase after API endpoints stabilize |
| Mobile (Flutter) | SDK not installed on dev machine |
| Voice, offline sync, load testing, deployment | Depend on above |
