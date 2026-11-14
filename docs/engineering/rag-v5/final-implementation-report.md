# RAG V5 — final implementation report (2026-11-15)

## 1. Release recommendation

**`IMPLEMENTATION PARTIALLY COMPLETE — RELEASE BLOCKED`** for the full V5
vision, with the executed vertical slice complete for the verified
environment and **zero regression to the serving default**. Per the
Master Prompt §18 this is the honest state: the architecture, persistence
and verification scaffolding are implemented and tested; three gates are
blocked by named owner dependencies (below). The existing application is
unaffected (feature-lock register; full suites green; defaults unchanged).

## 2. Repository state

- Branch `feat/rag-v5-semantic-pgvector` from main `c944164`; commits this
  wave: migration/lifecycle (W3/W4), neural adapter + verification modes
  (W2/W7), seams/env-example fixes, docs.
- Worktree clean at report time; all changes via reviewed PR.

## 3. Implemented (evidence)

1. **Generation registry + atomic activation** (W3/W4): migration
   `c7d9e1f3a5b7` (engine-conditional); `GenerationManager`; tests 8/8
   incl. chain-linear + downgrade legs. `alembic check`: no drift.
2. **PgVectorStore** (W3): exact cosine, metadata filters in SQL,
   idempotent upsert, validation, isolation, retirement; CI switched to
   `pgvector/pgvector:pg16`; `tests/test_pgvector_store.py` — real
   extension in CI (Gate P1 path), explicit skip-with-reason locally
   (`NOT_RUN` locally is recorded, never claimed).
3. **Neural adapter** (W2): identity contract, E5 prefixes, dim/finite
   validation, batching, lazy backend; factory branch + guards; 4 tests
   with injected backend (no network, no download).
4. **Verification modes** (W7): off/shadow/enforce + approval flag;
   additive `verification_status`; 4 tests incl. boot refusals.
5. **Docs**: baseline-audit, feature-lock-register, benchmark-protocol
   (pre-registered v1), implementation-plan, pgvector-and-index-lifecycle,
   evidence-verification, operations-runbook, execution-log.

## 4. Blockers (exact, per §18)

| Gate | Blocked by | Single next owner action |
|---|---|---|
| Class 6 serving index (`BLOCKED_SOURCE_OR_RIGHTS`) | approved Class 6 textbook not ingested (quarantined source) | deliver the `.docx` |
| Model/reranker selection (E1/E2) | no human-reviewed Class 6 labels (`BLOCKED_OWNER_DATA`) | commission the Bangla educator label review |
| pgvector staging/production activation (`BLOCKED_INFRA`) | production host = SQLite; no Postgres host provisioned | provision a pgvector-capable host |
| Canary/production rollout | explicit owner approval required by the prompt's default release state | decide after the above three |

## 5. Serving default — unchanged (proven)

`hybrid` (BM25 ∥ HashingEmbedder, RRF k=60, lexical rerank, grounding
gate, top-3) remains the one and only serving mode. Full API suite 2259
passed / 16 skipped; web suite 115 files / 524 tests; every mode added is
explicit, non-default and boot-guarded. No student-data egress path was
opened; no corpus content was committed; the schema adds curriculum-vector
and lifecycle tables only (no student data — feature-lock register).
