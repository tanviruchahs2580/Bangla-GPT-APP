# RAG V5 — pgvector storage and index lifecycle (as-built)

## Schema (migration `c7d9e1f3a5b7`, engine-conditional)

- `rag_index_generations` — registry: generation_id (PK), state
  (`building|validated|active|retained|retired|failed`), corpus_digest,
  embedder_name + revision, dimension, bm25_artifact_sha256, chunk_count,
  validated/activated/retired/created timestamps. State column indexed.
- `rag_active_generation` — single-row pointer (singleton=1), swapped in
  one transaction by `GenerationManager.activate`.
- `rag_vector_chunks` — **PostgreSQL only** (requires `vector`):
  (generation_id, chunk_id) PK, source_id, class_level, subject, chapter,
  `embedding vector(384) NOT NULL`, created_at. Metadata indexes for the
  server-side filters. Dimension strategy: fixed 384 (HashingEmbedder and
  multilingual-e5-small are both 384); a different model dimension
  requires a reviewed migration (V5 §6.3 fixed-dimension option).
- SQLite: registry + pointer exist (local lifecycle runs); the vector
  chunks table is skipped — SQLite keeps the in-memory VectorIndex and no
  test claims pgvector semantics from SQLite.

## Generation identity

`GenerationManager` binds: corpus digest, embedder name/revision,
dimension, BM25 artifact digest (recorded at validation), chunk count, and
state timestamps. Activation requires state `validated`; the pointer swap
and the state flip share one transaction; the previously active generation
moves to `retained` (rollback = a pointer flip + re-activation of the
retained row).

## BM25 coherence

The BM25 lane remains process-local for the current default mode. The
generation contract requires the BM25 artifact for a generation to record
its digest (`bm25_artifact_sha256` at validation) and the worker to pin
the generation it loaded — enforced by the boot-time identity checks that
already refuse an embedder/corpus mismatch (F-129/RAG-11). The BM25
artifact persistence itself is the next-wave build-lifecycle item
(`NOT_RUN`).

## Failure semantics implemented

- `activate` on a non-validated generation → `GenerationStateError`.
- Re-building under an ACTIVE generation id → refused (ids immutable).
- `PgVectorStore.__init__` without the table → `PgVectorUnavailable`
  (never an in-memory substitution).
- `validate` returns explicit problems: count mismatch, dimension
  mismatch, orphaned rows.
- Retirement deletes only the named generation's rows; the active
  generation is untouched (tested).

## ANN decision

Exact `<=>` search is the reference implementation (V5 §6.3). At 847
chunks (and any plausible Class 6 scale), exact search is the initial
mode; HNSW/IVFFlat require a measured latency/recall justification on the
real corpus — recorded as deferred, not silently absent.
