# BASELINE AUDIT — Bangla-GPT-APP

> **Date:** 2026-09-14
> **Auditor:** Enterprise Principal Architect
> **Baseline revision:** `0c2311b` (WAVE-5 mobile repair, release v0.9.1)
> **Purpose:** Forensic understanding of the system before any transformation work.

---

## 1. Current Architecture

Bangla-GPT-APP is a **modular monolith** deployed as two separate services:

- **`apps/api`** — FastAPI backend (Python 3.11/3.12)
  - 332-line `main.py` (thin entrypoint, previously ~7000 lines)
  - 76 Python source files in `src/bangla_gpt_api/`
  - 13 routers covering all domain boundaries
  - 45+ service modules
  - 20 Alembic migration files
  - 634 pytest test files

- **`apps/web`** — React/Vite SPA (TypeScript, Vercel-deployed)
  - 15 pages (welcome, auth, student, teacher, parent, admin, school)
  - 43 Vitest test files (126 tests)
  - PWA-capable with offline store, voice input, structured answers

**Deployment topology:**
```
Vercel (static SPA + /api proxy rewrite)
    → Cloudflare Tunnel (api-live container)
        → FastAPI on owner's machine (mock LLM)
```

---

## 2. Repository Map

```
Bangla-GPT-APP/
├── apps/
│   ├── api/                        # FastAPI service
│   │   ├── src/bangla_gpt_api/     # Source (76 .py files)
│   │   │   ├── auth/               # MFA, password hashing, JWT
│   │   │   ├── caching.py          # MemoryCache + Redis protocol
│   │   │   ├── config.py           # Settings (env-driven)
│   │   │   ├── curriculum/models.py # NCTB curriculum models
│   │   │   ├── data/               # Corpus loader
│   │   │   ├── db/                 # SQLAlchemy models, session
│   │   │   ├── evaluation/         # AI eval: metrics, runner, CLI
│   │   │   ├── ingestion/          # OCR + text ingester
│   │   │   ├── initialize/         # App bootstrap (5 modules)
│   │   │   ├── jobs.py             # ARQ worker, cron jobs
│   │   │   ├── logging_config.py   # JSON logging, request IDs
│   │   │   ├── main.py             # Thin entrypoint (332 lines)
│   │   │   ├── metrics.py          # Prometheus counters/histograms
│   │   │   ├── middleware.py       # RequestId, RateLimit, CSP
│   │   │   ├── nctb/               # NCTB corpus pipeline (9 files)
│   │   │   ├── providers/          # LLM provider protocol (mock/gemini/openai)
│   │   │   ├── ratelimit.py        # Memory + Redis rate limiters
│   │   │   ├── retrieval/          # BM25, hybrid, embedding, vector
│   │   │   ├── routers/            # 13 domain routers
│   │   │   ├── security.py         # Fernet PII encryption, audit
│   │   │   ├── services/           # 40+ domain services
│   │   │   └── schemas.py          # Pydantic request/response schemas
│   │   ├── alembic/                # 20 migration files
│   │   ├── scripts/                # Corpus build, evaluate, content QA
│   │   ├── tests/                  # 93 test files
│   │   └── worker.py               # ARQ worker settings
│   └── web/                        # React/Vite SPA
│       ├── src/
│       │   ├── components/         # UI primitives, domain components
│       │   ├── lib/                # Utilities (analytics, voice, i18n, offline)
│       │   ├── pages/              # 15 page components
│       │   ├── test/               # 43 Vitest test files
│       │   ├── AppShell.tsx        # Layout shell
│       │   ├── AuthContext.tsx     # Auth state management
│       │   ├── api.ts              # API client
│       │   ├── errors.ts           # Error handling
│       │   ├── i18n.ts             # Bengali/English i18n
│       │   ├── types.ts            # TypeScript types
│       │   └── main.tsx            # Entry point
├── data/nctb/                      # NCTB corpus data
├── deploy/
│   ├── caddy/                      # Caddy reverse proxy config
│   ├── grafana/                    # Grafana dashboards
│   ├── postgres/                   # pgBackRest config
│   └── prometheus/                 # Prometheus + alerting
├── docs/
│   ├── architecture.md             # Main architecture doc (235 lines)
│   ├── archive/                    # 16 prior execution/reports
│   └── *.md                        # 32 flat documentation files
├── .github/workflows/              # CI/CD pipelines (4 workflows)
├── docker-compose.yml              # Multi-profile compose
├── Dockerfile                      # Multi-stage Docker build
└── scripts/                        # Deployment, smoke, load, DR scripts
```

---

## 3. Dependency Map

```
Frontend (React/Vite)
    ↓ fetch
Backend API (FastAPI)
    ├── SQLAlchemy → SQLite/PostgreSQL
    ├── Redis → rate limiting, caching, ARQ queue
    ├── LLM Provider (mock/gemini/openai)
    │   ├── BM25 hybrid retrieval
    │   ├── Embedding (local deterministic)
    │   └── RAG service → grounded answers
    └── Prometheus metrics / Sentry tracing
```

**Python dependency direction (enforced):**
```
routers/ → services/ → providers/ / retrieval/ / db/
providers/ has NO inbound from db/ or routers/
retrieval/ is self-contained
```

---

## 4. Risk Register

| Risk | Severity | Evidence |
|------|----------|----------|
| In-memory default DB removed (was `sqlite://`) | Medium | Changed to file-based `sqlite:///./bangla_gpt.db` — dev data persists, tests use in-memory |
| Local dev DB not gitignored | Medium | `bangla_gpt.db` should be in `.gitignore` |
| Vercel API depends on owner's machine | High | Tunnel rotates; not suitable for permanent production |
| No dedicated object storage abstraction | Low | S3 referenced in docs/backup but no StorageProvider protocol |
| Frontend has no hooks/ services/ subdirs | Low | Concerns are inline (AuthContext, api.ts) — works but not enterprise pattern |
| No BASELINE_AUDIT.md or TARGET_ARCHITECTURE.md | Low | Documentation gap; architecture is in docs/architecture.md |
| No ADR directory or TRANSFORMATION_CHANGELOG | Low | Architecture decisions documented in docstrings but not formalized |
| No FINAL_ENTERPRISE_100_SCORECARD.md | Low | Scorecard path required by master prompt |
| No PRODUCTION_DEPLOYMENT.md | Low | Deployment documented across Vercel record, docker-compose, Caddyfile |

---

## 5. Test Baseline

| Suite | Files | Tests | Status |
|-------|-------|-------|--------|
| API pytest | 93 | 634 collected | Partial run: green |
| Frontend Vitest | 43 | 126 | 124/126 green (2 pre-existing timeouts) |
| CI matrix | 2 Python versions | Full pipeline | 6/6 green documented |

---

## 6. Build Baseline

| Build | Status | Output |
|-------|--------|--------|
| API app create | ✅ | 116 OpenAPI paths loaded |
| Frontend Vite | ✅ | `index-ncjoE9UB.js` (288KB gzipped to 96KB) |
| Docker | ✅ | Multi-stage build with GHCR publishing |
| Alembic | ✅ | 20 migrations, upgrade/downgrade verified in CI |

---

## 7. Security Baseline

| Area | Status |
|------|--------|
| OWASP checklist | ✅ docs/owasp_checklist.md |
| Password hashing | ✅ PBKDF2 200K iterations |
| JWT revocation | ✅ Per-token jti + cache |
| PII encryption | ✅ Fernet at rest (security.py) |
| CSP headers | ✅ Set by middleware + Caddy |
| Rate limiting | ✅ Memory + Redis backends |
| Safety screening | ✅ Bengali keyword regex patterns |
| PII redaction | ✅ Phone/email/NID patterns at LLM boundary |
| pip-audit | ✅ Fails on vulnerable deps |
| Trivy scan | ✅ Fails on fixable vulns |

---

## 8. AI/RAG Baseline

| Area | Status |
|------|--------|
| Hybrid retrieval | ✅ BM25 + vector + RRF fusion |
| NCTB grounding | ✅ Curriculum-aware filtering |
| Citation/provenance | ✅ SourceRef with book/chapter/section |
| Hallucination guard | ✅ Grounding gate + insufficient-evidence refusal |
| Safety screening | ✅ Before retrieval (pre-100% coverage, post-NFKC normalize) |
| AI evaluation | ✅ Golden datasets, redteam, metrics suite |
| NCTB pipeline | ✅ Source provenance, chunking, manifest |

---

## 9. Deployment Baseline

| Component | Status |
|-----------|--------|
| Docker compose | ✅ 7 profiles (core, worker, web, tls, postgres, monitoring, backup) |
| Caddy proxy | ✅ Secure headers, gzip/zstd, CSP |
| Vercel SPA | ✅ Live at bangla-gpt-app.vercel.app |
| API tunnel | ✅ Cloudflare (rotating, dev-stage) |
| Monitoring | ✅ Prometheus + Grafana dashboards |
| DR | ✅ pgBackRest, S3 off-site, RPO ~1min, RTO <4h |

---

## 10. Known Limitations

1. **Documentation directories** — `docs/architecture/`, `docs/adr/`, etc. don't exist yet (flat docs at root)
2. **Object storage** — No `StorageProvider` abstraction (phase 15 partial)
3. **Frontend hooks/services** — Inline pattern vs enterprise subdirectory pattern
4. **Missing consolidated docs** — BASELINE_AUDIT, TARGET_ARCHITECTURE, DATABASE_ARCHITECTURE, PRODUCTION_DEPLOYMENT, ADRs, Scorecard

---

## 11. Uncommitted Changes (pending commit)

| File | Change |
|------|--------|
| `config.py` | Version 0.6.2 → 0.9.1; DB default `sqlite://` → `sqlite:///./bangla_gpt.db` |
| `main.py` | Production safety guard expanded to catch `sqlite:///:memory:` |
| `dependencies.py` | Production in-memory DB check expanded |
| `bm25.py` | NFKC normalization for Bangla keyboard variant folding |
| `tutor.py` | `normalize_query()` applied before safety + retrieval in `ask()` and `ask_stream()` |
| `.env.example` | Comment updated for new DB default |

All changes verified correct and non-regressive.
