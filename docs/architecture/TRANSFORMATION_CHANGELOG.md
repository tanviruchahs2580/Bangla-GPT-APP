# TRANSFORMATION CHANGELOG — Bangla-GPT-APP

> Enterprise 100/100 Transformation tracking log

---

## CHANGE LOG

| Change ID | Phase | Date | Problem | Root Cause | Files | Change | Risk | Tests | Result | Rollback | Status |
|-----------|-------|------|---------|------------|-------|--------|------|-------|--------|----------|--------|
| CHG-001 | 0-1 | 2026-09-14 | Documentation directories missing | Flat docs at root | Created `docs/architecture/`, `docs/adr/`, `docs/api/`, `docs/ai/`, `docs/data/`, `docs/security/`, `docs/operations/`, `docs/testing/` | Created required directory structure per master prompt | Low | N/A | Docs created, no code changes | N/A | Done |
| CHG-002 | 0 | 2026-09-14 | No BASELINE_AUDIT.md | New system, baseline never documented | Created `docs/architecture/BASELINE_AUDIT.md` | Comprehensive baseline with architecture map, dependency map, risk register, test/build/security/AI/RAG/deployment baselines | Low | N/A | Baseline complete | N/A | Done |
| CHG-003 | 1 | 2026-09-14 | No TARGET_ARCHITECTURE.md | Architecture decisions implicit | Created `docs/architecture/TARGET_ARCHITECTURE.md` | Full bounded contexts, layer architecture, AI/RAG pipeline, dependency direction, data ownership, API boundaries, security boundary, deployment topology | Low | N/A | Architecture documented | N/A | Done |
| CHG-004 | 5 | 2026-09-14 | No DATABASE_ARCHITECTURE.md | Schema known but not documented | Created `docs/architecture/DATABASE_ARCHITECTURE.md` | Dev/staging/prod DB config, migration process, schema overview, index strategy, transaction integrity, backup/restore strategy, data provenance | Low | N/A | Database architecture documented | N/A | Done |
| CHG-005 | 22 | 2026-09-14 | No PRODUCTION_DEPLOYMENT.md | Deployment info scattered | Created `docs/operations/PRODUCTION_DEPLOYMENT.md` | Environment matrix, reproducible build steps, deployment procedures (Docker/Vercel/GHCR), startup validation, security config, rollback procedure, smoke tests | Low | N/A | Production deployment documented | N/A | Done |
| CHG-006 | 24 | 2026-09-14 | No ADR governance | Architecture decisions not formalized | Created `docs/adr/ADRs.md` | 9 ADRs: modular monolith, LLM provider abstraction, hybrid retrieval, safety screening, SQLite default, NFKC normalization, two-service deployment, PBKDF2+JWT revocation, Fernet PII encryption | Low | N/A | ADR governance framework created | N/A | Done |
| CHG-007 | 24 | 2026-09-14 | No TRANSFORMATION_CHANGELOG.md | Change tracking missing | Created this file | Comprehensive change log with problem/root cause/impact tracking | Low | N/A | Change management established | N/A | Done |
| CHG-008 | 26 | 2026-09-14 | No FINAL_ENTERPRISE_100_SCORECARD.md | Scorecard path required by master prompt | Created `docs/FINAL_ENTERPRISE_100_SCORECARD.md` | Full 110-point scorecard normalized to 100, with evidence-backed scoring per category | Low | N/A | Enterprise scorecard complete | N/A | Done |
| CHG-009 | 0 | — | In-memory DB default risk | `sqlite://` default could leak to production | `config.py`, `main.py`, `dependencies.py`, `.env.example` | Default changed to `sqlite:///./bangla_gpt.db`; production safety guards expanded to catch all `:memory:` variants | Medium | All safety + production tests | Production in-memory DB blocked | Revert default URL | Done |
| CHG-010 | 10 | — | Bangla query-retrieval mismatch | Mobile keyboard NFKC variants bypass BM25 | `bm25.py`, `tutor.py` | NFKC normalization in BM25 tokenizer and `normalize_query()` in `TutorService.ask()` and `.ask_stream()` | Low | BM25 tokenizer tests, safety test coverage | Index/query symmetry restored | N/A | Done |
| CHG-011 | 4 | — | Version drift | `config.py` fallback had stale version 0.6.2 | `config.py` | Bumped to 0.9.1 matching pyproject.toml and release tag | Low | Version check in settings tests | Version consistency restored | N/A | Done |
