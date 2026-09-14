# TARGET ARCHITECTURE — Bangla-GPT-APP

> **Date:** 2026-09-14
> **Status:** Implemented — all bounded contexts exist and are operational

---

## 1. Bounded Contexts

| Context | Module | Responsibility |
|---------|--------|----------------|
| **Auth** | `auth/` | Registration, login, MFA, password reset, TOTP |
| **Users** | `routers/users.py` + `db/models.py` | User profiles, roles, consent management |
| **Students** | `routers/learn.py` + `services/learn.py` | Student learning journey, progress |
| **Teachers** | `routers/teacher.py` + `services/generators/` | Class management, AI content generation |
| **Parents** | `routers/parent.py` + `services/parent_digest.py` | Child linking, consent, digest reports |
| **Schools** | `routers/school.py` | School onboarding, classrooms, staff |
| **Admin** | `routers/admin.py` | Platform admin, triage, moderation |
| **Tutor/AI** | `routers/tutor.py` + `services/tutor.py` | Grounded Q&A, conversation |
| **Quiz/Assessment** | `routers/assessment.py` + `services/quiz.py` | Quiz creation, attempts, explain |
| **NCTB Corpus** | `nctb/` + `data/` | Ingestion, chunking, provenance |
| **Retrieval** | `retrieval/` | BM25, hybrid, embedding, fusion |
| **LLM Providers** | `providers/` | Protocol + mock/gemini/openai |
| **Safety** | `services/safety.py` | Content screening, PII redaction |
| **Jobs** | `jobs.py` + `worker.py` | Async tasks, cron, ARQ queue |
| **Observability** | `logging_config.py`, `metrics.py` | JSON logs, Prometheus, Sentry |

---

## 2. Layer Architecture

```
┌──────────────────────────────────────────────────┐
│  Web / PWA (React + Vite + Vercel)               │
│  pages/ components/ lib/ hooks (inline)          │
└────────────────────────┬─────────────────────────┘
                         │ HTTP / SSE / WebSocket
┌────────────────────────▼─────────────────────────┐
│  API — FastAPI Entrypoint (main.py, 332 lines)   │
│  ┌─────────────┐ ┌──────────────┐ ┌────────────┐│
│  │ Middleware  │ │ CORS/SPF/CSH │ │ Request ID ││
│  └──────┬──────┘ └──────┬───────┘ └─────┬──────┘│
│         │                │               │        │
│  ┌──────▼────────────────▼───────────────▼──────┐│
│  │  Routers (13 domain routers)                 ││
│  │  admin / assessment / auth / common / learn  ││
│  │  parent / school / system / teacher / tutor  ││
│  │  users / workspace                           ││
│  └──────────────────┬──────────────────────────┘│
│                     │                            │
│  ┌──────────────────▼──────────────────────────┐│
│  │  Application Services (45+ modules)        ││
│  │  tutor / learn / quiz / safety / knowledge  ││
│  │  generators/ (lesson plan, quiz, homework)  ││
│  │  circuit_breaker / mailer / cost tracking   ││
│  └──────────────────┬──────────────────────────┘│
│                     │                            │
│  ┌──────────────────▼──────────────────────────┐│
│  │  Domain Layer                                ││
│  │  curriculum/models / db/models              ││
│  └──────────────────┬──────────────────────────┘│
│                     │                            │
│  ┌──────────────────▼──────────────────────────┐│
│  │  Infrastructure                              ││
│  │  providers/  retrieval/  caching/            ││
│  │  db/session  ingestion/  ratelimit/          ││
│  └─────────────────────────────────────────────┘│
└──────────────────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────┐
│  Persistence & Services                           │
│  SQLite (dev) / PostgreSQL (prod)                │
│  Redis (rate limit / cache / ARQ queue)          │
│  S3/MinIO (future object storage)                │
└──────────────────────────────────────────────────┘
```

---

## 3. AI/RAG Pipeline Boundary

```
User Query (bn/en)
    ↓
normalize_query()        ← NFKC normalization (Unicode variant folding)
    ↓
_screen_safety()         ← Bengali keyword regex (pre-retrieval gate)
    ↓
retrieve(query, class, subject, chapter)  ← hybrid BM25 + vector + RRF
    ↓
_coverage_gate(hits)     ← minimum evidence threshold
    ↓
build_evidence_prompt()  ← PII redaction (phone/email/NID)
    ↓
LLM provider.generate(evidence + question)
    ↓
grounding validation     ← citation check + confidence scoring
    ↓
Response (with provenance)
```

---

## 4. Dependency Direction (enforced)

```
routers/  →  services/  →  providers/ / retrieval/ / db/
services/ →  providers/ / retrieval/ / db/
providers/ ← (leaf, no inbound from routers or services)
retrieval/ ← (leaf, self-contained)
db/      ← (leaf, ORM models only)
middleware/ → no inbound from domain layers
```

**Zero circular dependencies** between domain modules.

---

## 5. Data Ownership

| Data | Owned By | Access |
|------|----------|--------|
| User accounts | Auth service | Self + admin |
| Conversations | Tutor service | Self + teacher |
| Quiz attempts | Assessment service | Self + teacher |
| NCTB corpus | NCTB pipeline | Read-only, filtered by class/subject |
| Audit logs | Security module | Admin only |
| Job runs | Jobs module | Self (claim_period idempotency) |
| Parent-child links | Parent service | Self + linked parent |
| School/staff | School service | Within school boundary |

---

## 6. API Boundaries

All 116 routes registered via `register_routers()` in `routers/__init__.py`.

**Authentication-required routes:** All domain routes except `/health`, `/live`, `/ready`, `/register`, `/login`, `/forgot-password`, `/reset-password`, `/legal`, `/status`.

**CORS:** Configured via `ALLOWED_ORIGINS` env var, validated at startup.

---

## 7. Security Boundary

| Boundary | Implementation |
|----------|---------------|
| Transport | TLS via Caddy (prod); HTTP for local dev |
| Auth | JWT with per-token jti revocation |
| AuthN | PBKDF2 200K + MFA/TOTP optional |
| AuthZ | `require_roles()` decorator + school_id tenant filter |
| Input | Pydantic validation on all endpoints |
| Output | CSP headers, PII redaction, safe error messages |
| Secrets | env-driven, `.env` gitignored, no hardcoded values |

---

## 8. Async Job Boundary

```
HTTP POST → return job_id (202)
    ↓
ARQ queue (Redis-backed)
    ↓
worker.py processes job
    ↓
JobRun table tracks status (pending/running/completed/failed)
    ↓
WebSocket/SSE polls status or webhook notification
```

Cron jobs: `run_weekly_digest()`, `run_nightly_rollup()`, `run_retention_sweep()`.

---

## 9. Observability Boundary

| Signal | Implementation | Export |
|--------|---------------|--------|
| Logs | JSON structured with request_id | stdout → Caddy/PM2 |
| Metrics | Prometheus counters/histograms | scrape → Grafana |
| Tracing | Sentry integration | Sentry dashboard |
| Health | /health, /live, /ready | Prometheus probe |

---

## 10. Deployment Topology

```
                    ┌─────────────┐
                    │   Vercel    │
                    │  (SPA +     │
                    │   /api      │
                    │   rewrite)  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │Cloudflare   │
                    │  Tunnel     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  API VM     │
                    │  FastAPI    │
                    │  + Redis    │
                    │  + SQLite   │
                    └─────────────┘
```

**Production (full):** Docker Compose with Caddy TLS, PostgreSQL, Redis, Prometheus, Grafana, pgBackRest backups.
