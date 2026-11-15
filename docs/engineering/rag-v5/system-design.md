# Bangla GPT — full RAG system design (as-built 2026-11-15, wave V5.5)

This is the single-map document for the tutor's retrieval stack: what
exists, what is dormant, what is blocked, and how each stage maps to the
current best practice (see `docs/references/rag/README.md` for the
sources). Serving runs on the live single-host container; staging here
means the local pgvector lane built in wave V5.5.

## 1. Pipeline at a glance

```
student question (bn / banglish / en, optional image)
  │
  ├─ normalize            NFKC + zero-width strip, offset map preserved
  │                       (retrieval/normalize.py)
  ├─ legacy input         Bijoy/SutonnyMJ detect + convert (nctb/bijoy.py)
  ├─ safety screen        7 categories, bn/banglish/en, BEFORE retrieval
  │                       (services/safety.py) → age-appropriate refusal
  ├─ retrieve             HybridIndex: BM25 ∥ dense, RRF k=60 fusion,
  │                       lexical rerank, top-3 (retrieval/hybrid.py)
  │                       vector-only candidates must share Bangla bigrams
  ├─ grounding gate       IDF-weighted coverage ≥ 0.5 AND < 2 absent
  │                       content terms, else INSUFFICIENT_EVIDENCE_ANSWER
  ├─ generate             tutor-prompt-v1 (bn, 8 numbered rules), evidence
  │                       in <evidence> delimiters + sanitize_evidence,
  │                       question in <user_question>, image in
  │                       <attached_image>; streamed; PII-redacted egress
  ├─ verify               citation_check (every marker resolves to the
  │                       retrieved set) → verification_status
  │                       off | shadow | enforce (enforce boot-gated)
  └─ record               answer_log (730d), ai_usage (365d), prompt
                          version + sha256 on every answer, metered
```

## 2. Stage-by-stage: state and modern-stack mapping

| Stage | Implementation | Modern practice | State |
|---|---|---|---|
| Chunking | structure-aware, 220/60/450 tokens, no overlap, SourceSpan offsets | structure-aware, size-bounded, provenance-carrying | **live** |
| Sparse index | BM25 (Bangla-block-aware tokenizer `[\w\u0980-\u09FF]+`) | BM25 remains the strongest sparse baseline | **live** |
| Dense index | HashingEmbedder 384-d (char-ngram, deterministic) | trained dual-encoder (DPR) | **live (stand-in)**; trained encoder **blocked** on human-reviewed labels |
| Vector store | SQLite era: in-process; Postgres: pgvector `vector(384)`, exact `<=>`, generation-bound rows | pgvector exact at small scale = perfect recall; ANN (HNSW) only at scale | **live primitive; staging-active; production blocked** on Postgres host |
| Fusion | RRF k=60 (no score normalization, no tuning) | field-standard constant (Cormack 2009) | **live** |
| Rerank | lexical rerank (live); cross-encoder + query expansion knobs | cross-encoder rerank (bge-reranker class) | **dormant** — sweep found defaults within noise; activation needs the benchmark protocol |
| Query enhancement | Banglish transliteration + bounded fuzzy (retrieval/transliteration.py) | pre-retrieval query rewriting | **live (bn-specific)**; further rewriting **dormant** |
| Grounding | IDF coverage ≥ 0.5, < 2 absent terms, refusal is a correct outcome | faithfulness gate before generation | **live, ratchet** |
| Verification | citation_check deterministic; shadow status additive | RAGAS-style faithfulness | **shadow-ready**; enforce **blocked** on calibration data |
| Prompt | tutor-prompt-v1, versioned + hashed on every answer | versioned prompt identity | **live**; review in wave V5.5 |
| Eval | golden v3 (427) + 24Q gate + redteam + >2pp regression gate | golden sets + regression gates | **live**; real-corpus coverage gap recorded (audit) |
| Observability | structured events, ai_usage metering, per-answer trace | metrics + traces | **live**; counters proposed in benchmark-protocol (PROPOSED) |

## 3. Index lifecycle (V5)

One `index_generation_id` binds corpus digest + embedder identity +
dimension + BM25 artifact hash. States: `building → validated → active →
retained → retired | failed`. Activation is a one-transaction pointer
swap; the previous generation is retained for rollback; retirement
deletes only non-active rows. The embedder identity is verified at boot
(`_verify_embedder_identity`) — a corpus built with a different embedder
or dimension is refused. Build procedure:
`docs/engineering/rag-v5/operations-runbook.md` + the V5.5 build CLI
(`apps/api/scripts/build_index_generation.py`).

## 4. Topology

| Lane | Engine | Retrieval | Purpose |
|---|---|---|---|
| Production (live) | SQLite, single host | hybrid in-process | serving; unchanged by V5/V5.5 |
| Staging (this machine) | Docker `pgvector/pgvector:pg16` (port 5433, `bgpt-pgvector-staging`) | PgVectorStore over a real generation | proves the vector lane with real data |
| CI | pgvector service container | same | integration tests per PR |

Production pgvector serving remains **blocked** (`BLOCKED_INFRA`): it
requires a Postgres host, a built+validated generation, and an explicit
owner activation decision — in that order.

## 5. Honest gaps (next-wave queue)

1. **Serving-path pgvector wiring** — make the hybrid index able to take
   its dense lane from `PgVectorStore` when configured; requires the
   eval gate to stay green and a Postgres host to matter.
2. **Real-corpus eval coverage** — the blocking golden gate measures the
   synthetic sample; a real-corpus golden set needs owner-reviewed
   Bangla items (same dependency as the label gate).
3. **Trained embedder + cross-encoder** — both wait on the pre-registered
   benchmark protocol with human-reviewed labels.
4. **Class 6 corpus** — the approved `.docx` unblocks ingestion; until
   then the corpus is HSC/secondary physics-etc. (847 chunks, no class
   metadata beyond source `level`).
5. **DPIA** — governance gap for a children's-data product (unchanged).
