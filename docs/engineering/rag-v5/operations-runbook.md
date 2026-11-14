# RAG V5 operations runbook (as-built slice)

## Build a generation (PostgreSQL + pgvector host)

Current wave ships the lifecycle primitives; the full resumable build CLI
is the next-wave item (`NOT_RUN`). The primitives are exercised by
`tests/test_pgvector_store.py` (CI pgvector leg):

```python
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.retrieval.generation import GenerationManager, PgVectorStore

engine = make_engine(settings)
manager = GenerationManager(make_session_factory(engine))
manager.create_building(generation_id="g-2026-11-15", corpus_digest="…",
                        embedder_name="neural:intfloat/multilingual-e5-small@v1",
                        dimension=384)
store = PgVectorStore(engine, "g-2026-11-15")
store.upsert(rows)                      # idempotent batches (chunk_id, source, class, subject, chapter, vec)
problems = store.validate(expected_count=N, dimension=384)
assert not problems
manager.mark_validated("g-2026-11-15", chunk_count=N, bm25_artifact_sha256="…")
manager.activate("g-2026-11-15")        # atomic pointer swap; previous → retained
```

## Status / rollback / retirement

- Active generation: `GenerationManager.active_generation_id()` (or
  `SELECT * FROM rag_active_generation`).
- Rollback: re-activate the retained generation id (pointer flip; its
  rows are retained until retired).
- Retirement cleanup: `PgVectorStore(engine, old_id).delete_generation(old_id)`.
- Failure: `manager.mark_failed(id)` (never applied to an active row).

## Outage behavior (matrix from Master Prompt §8, implemented slice)

- Neural lane selected but backend missing → `ProviderNotInstalledNeural`
  at construction (no silent Hashing fallback).
- pgvector table/extension missing → `PgVectorUnavailable` (never an
  in-memory substitution on PostgreSQL).
- Invalid retrieval config (unknown verification mode/provider, enforce
  without approval) → boot refused (all environments).

## Backup/restore

`rag_index_generations` / `rag_active_generation` / `rag_vector_chunks`
are ordinary tables in the database backup path (runbook §4). Regeneration
from the corpus is always possible (deterministic pipeline), so vector
rows are rebuildable artifacts — restore priority is the DB itself.

## Monitoring (proposed, not provisioned)

`rag_generation_activated` / `rag_generation_created` structured events
already emit; counters for build progress and retrieval-stage latency are
proposed in benchmark-protocol.md §metrics — labelled `PROPOSED` until an
owner-approved SLO review (OPS-003 backlog item).
