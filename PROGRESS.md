# PROGRESS — Bangla GPT Master Roadmap v1.0

**Mode:** supervised · **Branch:** `upgrade/master-roadmap` · **Last updated:** 2026-09-04 · **Current:** S0.3
**Gates:** [ ] G0 · [ ] G1 · [ ] G2 · [ ] G3 · [ ] G4 · [ ] G5 · [ ] G6 · [ ] G7
**Human inputs:** GEMINI_API_KEY pending (S0.1 live verify blocked) · Staging server pending · Sentry DSN pending · Postgres/Redis/SMTP/NCTB/Android/School pending

## Stages & Steps (64)
- [x] **0.1 Real LLM provider (Gemini) live** | status: done (code+mocked tests green; live /ready gemini pending key) | evidence: gemini Generate/Stream now log latency_ms+prompt/answer chars+retries via json_log; pooled AsyncClient; pytest 172 passed; ruff/mypy clean | commit: 5e6ff4f
- [x] **0.2 Mock leak fix (AUD-01)** | status: done | evidence: mock.py already returns [mock] quoted evidence (no system); new test test_mock_never_leaks_system_prompt asserts no <evidence>/<user_question>/AUD-01 tokens; pytest 172 passed | commit: eb2955d
- [x] **0.3 Markdown + KaTeX rendering** | status: done | evidence: SafeMarkdown (react-markdown+remark-math+rehype-katex, XSS regex strip, katex CSS) wired into AITutorPage bubble + LearnChapterPage sections; vitest 10 passed (4 files) includes KaTeX+XSS tests; tsc clean; vite build green (katex chunk 392kB) | commit: 48bbabb
- [x] **0.4 Postgres migration** | status: done | evidence: engine now pool_pre_ping+pool_size=10 for postgres; alembic upgrade head d4e5f6a7b8c9 on pg16 (5433), downgrade -1 ↔ upgrade reversible, pytest test_postgres_smoke PASSED, full suite 172 passed; scripts/pg_backup.sh created + drill executed (docker pg) | commit: a4ae70a
- [x] **0.5 Config hardening** | status: done | evidence: enforce_production_safety now checks gemini key + CORS allowlist (no wildcard, must be set); negative test test_production_safety_rejects_weak_config covers JWT/Gemini/CORS; ruff/mypy clean | commit: —
- [ ] **0.3 Markdown + KaTeX rendering** | status: todo | evidence: — | commit: —
- [ ] **0.4 Postgres migration** | status: todo | evidence: — | commit: —
- [ ] **0.5 Config hardening** | status: todo | evidence: — | commit: —
- [ ] **0.6 Observability baseline** | status: todo | evidence: — | commit: — | 🖐 Sentry DSN
- [ ] **0.7 Real deploy + automated smoke** | status: todo | evidence: — | commit: — | 🖐 Staging server
- [ ] **1.1 /dashboard/summary + Continue + Recommendation v1** | status: todo | evidence: — | commit: —
- [ ] **1.2 Learn progress + Bookmark + TTS + font slider** | status: todo | evidence: — | commit: —
- [ ] **1.3 Unified Learning Workspace** | status: todo | evidence: — | commit: —
- [ ] **1.4 Structured AI response** | status: todo | evidence: — | commit: —
- [ ] **1.5 "আমি বুঝিনি" adaptive re-teach** | status: todo | evidence: — | commit: —
- [ ] **1.6 Source → evidence modal** | status: todo | evidence: — | commit: —
- [ ] **1.7 Quiz explain loop** | status: todo | evidence: — | commit: —
- [ ] **1.8 History search + rename/delete** | status: todo | evidence: — | commit: —
- [ ] **1.9 Streak + heatmap** | status: todo | evidence: — | commit: —
- [ ] **1.10 Spaced revision (SM-2)** | status: todo | evidence: — | commit: —
- [ ] **1.11 Global search v1** | status: todo | evidence: — | commit: —
- [ ] **1.12 Voice input** | status: todo | evidence: — | commit: —
- [ ] **1.13 Offline download + low-data mode** | status: todo | evidence: — | commit: —
- [ ] **1.14 PWA polish** | status: todo | evidence: — | commit: —
- [ ] **2.1 School/class data model** | status: todo | evidence: — | commit: —
- [ ] **2.2 Class management UI** | status: todo | evidence: — | commit: —
- [ ] **2.3 Content Engine** | status: todo | evidence: — | commit: —
- [ ] **2.4 Question Paper Generator (HIL)** | status: todo | evidence: — | commit: —
- [ ] **2.5 Short Test ultra-fast path** | status: todo | evidence: — | commit: —
- [ ] **2.6 Lesson Plan Copilot** | status: todo | evidence: — | commit: —
- [ ] **2.7 Weak heatmap + at-risk + support plan** | status: todo | evidence: — | commit: —
- [ ] **2.8 Bulk assign + tracking** | status: todo | evidence: — | commit: —
- [ ] **2.9 Question Bank** | status: todo | evidence: — | commit: —
- [ ] **3.1 School onboarding** | status: todo | evidence: — | commit: —
- [ ] **3.2 School Dashboard** | status: todo | evidence: — | commit: —
- [ ] **3.3 Curriculum coverage** | status: todo | evidence: — | commit: —
- [ ] **3.4 Parent weekly digest v1.5** | status: todo | evidence: — | commit: —
- [ ] **3.5 Admin Center v1.5** | status: todo | evidence: — | commit: —
- [ ] **4.1 Education Context Engine** | status: todo | evidence: — | commit: —
- [ ] **4.2 AI Model Router** | status: todo | evidence: — | commit: —
- [ ] **4.3 RAG v2** | status: todo | evidence: — | commit: —
- [ ] **4.4 Knowledge Graph v1** | status: todo | evidence: — | commit: —
- [ ] **4.5 Adaptive practice engine** | status: todo | evidence: — | commit: —
- [ ] **4.6 Weakness rollup** | status: todo | evidence: — | commit: —
- [ ] **4.7 Evaluation v2** | status: todo | evidence: — | commit: —
- [ ] **4.8 Safety v2** | status: todo | evidence: — | commit: —
- [ ] **5.1 Environments + IaC** | status: todo | evidence: — | commit: —
- [ ] **5.2 Zero-downtime deploy** | status: todo | evidence: — | commit: —
- [ ] **5.3 Redis** | status: todo | evidence: — | commit: — | 🖐 Redis
- [ ] **5.4 Background jobs (ARQ)** | status: todo | evidence: — | commit: — | 🖐 SMTP
- [ ] **5.5 Scale audit + load test** | status: todo | evidence: — | commit: —
- [ ] **5.6 Security hardening** | status: todo | evidence: — | commit: —
- [ ] **5.7 Backup / DR** | status: todo | evidence: — | commit: —
- [ ] **5.8 Compliance** | status: todo | evidence: — | commit: — | 🖐 Legal
- [ ] **5.9 Distribution** | status: todo | evidence: — | commit: — | 🖐 Android
- [ ] **5.10 Support ops** | status: todo | evidence: — | commit: —
- [ ] **6.1 NCTB corpus pipeline** | status: todo | evidence: — | commit: — | 🖐 NCTB PDFs
- [ ] **6.2 Content QA** | status: todo | evidence: — | commit: —
- [ ] **6.3 AI Classroom v1** | status: todo | evidence: — | commit: —
- [ ] **6.4 School analytics v2 + term report** | status: todo | evidence: — | commit: —
- [ ] **6.5 Govt/authority reporting** | status: todo | evidence: — | commit: —
- [ ] **6.6 Capacity plan** | status: todo | evidence: — | commit: —
- [ ] **6.7 Hosting decision** | status: todo | evidence: — | commit: — | 🖐 Sign-off
- [ ] **6.8 Load + chaos game-day** | status: todo | evidence: — | commit: —
- [ ] **7.1 Pilot** | status: todo | evidence: — | commit: — | 🖐 Schools
- [ ] **7.2 Teacher training kit** | status: todo | evidence: — | commit: —
- [ ] **7.3 Release train + graduation** | status: todo | evidence: — | commit: —

## Blockers
- None yet

## Evidence Log
- 2026-09-04: Branch created, PROGRESS initialized at S0.1
