# T-26 step 1-2: current retrieval flow + PostgreSQL Bangla verification

H-1 citations at `8717f6f`. Steps 3+ (model candidates → implementation) are **STOP S-4: the embedding-model choice waits for the owner** — this document is the prepared groundwork.

## Current retrieval flow (production lane)

1. **Corpus load**: NCTB chunks (1,598 live; bundled 78 sample in CI/tests) → `HybridIndex(chunks, build_embedder(settings))` (`initialize/dependencies.py`; identity logged at boot: `rag_corpus_identity` corpus/chunks/digest).
2. **Two lanes**: lexical `BM25Index` (`retrieval/bm25.py`, Bangla-block-aware tokenizer `retrieval/hybrid.py`) + vector `VectorIndex` over the `HashingEmbedder` — char n-gram hashing, blake2b, 384-dim, L2-normalized, NOT semantic (`retrieval/embedding.py:67-91`).
3. **Fusion**: reciprocal rank fusion (`retrieval/fusion.py`) → optional cross-encoder rerank (`retrieval/reranker.py`, off by default) → `top_k` (ceiling 3, boot-guarded).
4. **Grounding gate**: IDF-weighted coverage ≥ 0.5 AND < 2 absent content terms, else `INSUFFICIENT_EVIDENCE_ANSWER` (`services/tutor.py _coverage_details`; boot-guarded by `_validate_rag_grounding`).
5. **Identity enforcement**: `_verify_embedder_identity` refuses a corpus whose manifest embedder/dim differs (`retrieval/index_manifest.py:66-84`).
6. **Versioning**: index-generation registry + pgvector chunks table (migration `c7d9e1f3a5b7`, RAG V5); live corpus digest logged at boot.

## PostgreSQL Bangla verification (step 2, measured on the disposable pg16 container 2026-11-20)

- `vector` and `pg_trgm` extensions: **available and creatable** in `pgvector/pgvector:pg16` (CREATE EXTENSION ok).
- `to_tsvector('simple', 'কোষ বিভাজন ও বংশগতি')` → `'ও':3 'কোষ':1 'বংশগতি':4 'বিভাজন':2` — whitespace word tokenization; no Bengali-specific config exists (expected). **Decision (card-sanctioned default): lexical matching stores the Bangla normalizer's pre-normalized tokens and searches with `simple`** — a Bengali text-search configuration does not exist in PostgreSQL 16.
- `show_trgm('বংশগতি')` returns real trigrams — pg_trgm similarity works on Bangla strings (byte-level trigrams).
- ADR to carry into the implementation task: tokens pre-normalized by `retrieval/normalize.py`, stored in the text-search column, `simple` configuration; vector column `vector(384)` initially on the hashing embedder, swapped when the S-4 model choice lands.

## Step 3 (S-4): candidate classes for the owner (NOT downloaded, NOT chosen)

| Class | Examples (verify model cards at decision time — H-10) | License class | Notes |
|---|---|---|---|
| Multilingual lightweight | paraphrase-multilingual-MiniLM-L12-v2 / distiluse-base-multilingual-cased | Apache-2.0 | small, CPU-friendly; Bengali coverage claimed on cards — verify per card |
| Indic-focused | IndicBERT/SBERT variants | varies (verify) | Bengali-focused; smaller ecosystem |
| Hosted API | provider embedding APIs | SaaS (vendor DPA required) | violates the self-hosted-first policy unless owner accepts SaaS |

Every candidate must be measured here (CPU latency for 32-chunk batches + one query) before the owner chooses; no model is downloaded until the license is verified (card Never).

## Switch criteria (card step 6, recorded verbatim for the future task)
(a) on a HUMAN set, paired 95% CI lower bound for Recall@5 (new minus old) ≥ margin set at S-3 (default 0); (b) latency budget met; (c) memory per worker measured; (d) S-3 approval. Sets generated from corpus text never support a superiority claim.
