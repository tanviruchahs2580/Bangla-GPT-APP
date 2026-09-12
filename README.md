# Bangla GPT APP

**NCTB-grounded Bangla-first AI personal tutor platform.**

> **Status: v0.7.0 — world-class UI/UX renovation (Refined Bangladesh Green) + live reliability, CI green.**
> New in v0.7.0: full frontend visual/interaction renovation (design tokens, vector BrandMark, fluid Bangla typography, animated nav, tutor/quiz/learn polish, a11y + Lighthouse gates green), resilient nginx api proxy, analytics 401 funnel guard, version bump 0.6.2→0.7.0.
> **Status: v0.6.2 — Bangladesh Bangla language correction release (universal Bangla, CI green).**
> New in v0.6.2: Fix `test_health` version assertion to dynamic `Settings().version` (was hard-coded `0.6.0`), unblocking CI 3.11/3.12 matrix.
> v0.6.1 — Bangladesh Academy-standard Bangla across entire app (fixed 56 Assamese `ৰ`/`ৱ` glyphs, all CreateHub/Teacher UI strings: `ওয়ার্কশীট`, `উত্তরমালা`, `হোমওয়ার্ক`, `রুব্রিক`, `লেসন প্ল্যান`, `সেভ করা ডকুমেন্ট`, `মুছে ফেলুন` etc), distinct `প্রশ্নপত্র তৈরি করুন`/`পাঠ পরিকল্পনা তৈরি করুন` buttons, universal `Noto Sans Bengali` + `Hind Siliguri` font audit.
> v0.6.0 — NCTB AI Tutor blueprint release (5 roles incl. school_admin).
> New in v0.6: Bangladesh-green design system per the NCTB blueprint (AI-indigo
> accent, Noto Sans Bengali), welcome screen, unified teacher **Create hub**
> (worksheet / answer key / homework / rubric generators + async job queue
> Queued→Generating→Validating→Ready), persisted lesson plans & document
> library, workload-saved metric, **school_admin dashboard** (learning health,
> at-risk list, students/teachers/classes, curriculum coverage, usage), strict
> **school tenancy isolation**, tutor upgrades (strategy chips, numeric
> confidence badge, image-question path, save-to-notes), AI memory + learning
> preferences (view/edit/disable), in-app **notification bell** (short-test
> fan-out, job-ready), persisted analytics events, admin **AI-quality board**
> (grounding/refusal counts) and feedback triage, parent activity feed + AI
> report sentences — plus notification bell, i18n and error-copy fixes from
> live all-role user testing.
> v0.5 baseline: reader with bookmarks/TTS/font-size + offline chapter copies,
> quiz→tutor “explain this” deep-links, revision mini-quizzes + streak
> heatmap, teacher dashboards (classrooms, CSV roster import, take-home and
> per-student quiz assignments, AI question papers with review→finalize→PDF,
> short tests, lesson plans, support plans, weak-chapter matrix), parent
> per-chapter accuracy view, admin audit log, k-anonymised govt aggregate
> export, safety refusal panel, feedback triage, time-boxed revocable
> impersonation, public system-status page, unified chat/chapter search,
> dark mode + bn/en language toggles and authenticated JSON data export.
> v0.3/v0.4 baseline: multi-turn **tutor chat with SSE streaming + persisted history**, hybrid
> retrieval (Bangla light-stemming + query expansion + trigram fallback),
> child-safety moderation layer with supportive refusals, corpus covering
> classes 6–10 (science/mathematics/bangla), quiz honesty fields
> (`requested`/`partial_quiz` note), parent **invite-code** linking,
> email verification gate, per-user rate limiting, admin pagination/search +
> retention purge endpoint, answer 👍👎 feedback & privacy-safe events,
> redesigned responsive UI (design system, dark mode, self-hosted Bangla
> fonts), i18n scaffold (bn/en), PWA (installable + offline shell) and a
> frontend test suite (vitest).
> Student-facing পাঠ্যপুস্তক e-books still require rights-holder permission;
> live Gemini behaviour needs a real API key.

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

Full reference: [docs/API.md](docs/API.md). Operations: [docs/runbook.md](docs/runbook.md).
Launch gates for the owner: [docs/LAUNCH_READINESS_CHECKLIST.md](docs/LAUNCH_READINESS_CHECKLIST.md).
RAG design: [docs/RAG_ARCHITECTURE.md](docs/RAG_ARCHITECTURE.md).
NCTB pipeline: [docs/NCTB_DATA_PIPELINE.md](docs/NCTB_DATA_PIPELINE.md).

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
├── docs/archive/                             # superseded FINAL_* snapshots (history only)
├── BANGLA_GPT_ENTERPRISE_ARCHITECTURE_QA_AUDIT.md  # evidence-driven arch + QA audit
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
| `ci.yml` postgres job | alembic cycle + API journeys against Postgres 16 service container | ✅ active |
| `ci.yml` golden-eval job | golden retrieval benchmark w/ grounded-accuracy gate | ✅ active |
| `ci.yml` web job | Node 24 → npm ci → tsc + vite build | ✅ active |
| `ci.yml` docker job | build image → run → `/health` + `/ready` probes | ✅ active |
| `release.yml` | tag → GHCR images → optional SSH deploy w/ health-gated rollback | ✅ tag-driven |
| `repository-sanity.yml` | structure / secret-file / YAML validation | ✅ active |

Full roadmap: [docs/architecture.md](docs/architecture.md).

## License

[MIT](LICENSE)

