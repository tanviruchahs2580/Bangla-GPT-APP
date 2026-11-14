# RAG V5 implementation plan — dependency-ordered (executed 2026-11-15)

Statuses: `DONE` · `IN_PROGRESS` · `BLOCKED:<reason>` · `NOT_RUN`. Per the
Master Prompt §12/§17; blockers are isolated, never converted to passes.

| Task | Status | Notes |
|---|---|---|
| W0 repository safety: branch, baseline audit, feature-lock | DONE | baseline-audit.md, feature-lock-register.md; branch `feat/rag-v5-semantic-pgvector` from `c944164` |
| W1 Class 6 corpus scope verification | DONE (governance) | Scope-lock enforced: served corpus is the 9 curriculum sources; the Class 6 textbook is quarantined → real Class 6 serving index = `BLOCKED_SOURCE_OR_RIGHTS`; benchmark-protocol.md records the label gate |
| W1 benchmark foundation: protocol pre-registered | DONE | benchmark-protocol.md (v1, PROPOSED tolerances); runner extension deferred to the label-gated wave (NOT_RUN) |
| W2 neural adapter | DONE (code) | neural_embedder.py: identity contract, E5 prefixes, dim/finite validation, lazy backend, tests with injected backend; factory branch + boot guards. Selection = `BLOCKED_OWNER_DATA` |
| W3 pgvector store + migration | DONE (code) | migration c7d9e1f3a5b7 (engine-conditional), PgVectorStore, CI pgvector/pgvector:pg16 + integration tests (skip-with-reason locally, real in CI). Production activation `BLOCKED_INFRA` (live host = SQLite) |
| W4 generation lifecycle | DONE (core) | GenerationManager state machine + atomic pointer + retirement cleanup + tests. Resumable incremental build CLI: `NOT_RUN` (next wave) |
| W5 hybrid neural retrieval | `BLOCKED_OWNER_DATA` | Integration point exists (PgVectorStore contract = VectorIndex); serving default unchanged until benchmark gate passes |
| W6 cross-encoder | DONE (decision) | Lexical reranking retained with rationale: no adjudicated Bangla benchmark exists to measure an incremental gain (V5 §7.3) |
| W7 evidence verification | DONE (shadow) | off/shadow/enforce modes, deterministic verdict → additive `verification_status`; enforce boot-guarded; calibration `BLOCKED_OWNER_DATA` |
| W8 API/frontend compatibility | DONE | additive optional field only; OpenAPI fixture regenerated; web suite green |
| W9 observability + runbook + review | DONE (docs) | pgvector-and-index-lifecycle.md, evidence-verification.md, operations-runbook.md, execution-log.md; independent review pending → final report |
| Production rollout / canary | `BLOCKED_OWNER_APPROVAL` | Default release state honored: feature branch + merge only; no default activation, no staging (no authorized staging exists) |

## Owner actions that unblock the next wave

1. Deliver the approved Class 6 textbook (`.docx` route) → unblocks
   `BLOCKED_SOURCE_OR_RIGHTS` + the real benchmark (W1/W5).
2. Commission the Bangla educator label review → unblocks model selection
   (W2) and verifier calibration (W7).
3. Provision a PostgreSQL host with pgvector for staging → unblocks
   `BLOCKED_INFRA` activation (W3).
