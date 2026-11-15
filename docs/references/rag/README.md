# RAG reference base (downloaded 2026-11-15)

Curated summaries of the authoritative sources this project's retrieval
design is measured against. Each entry: provenance, the source's key
findings, and the specific relevance to Bangla GPT. Summaries are our
own notes from the linked pages (fetched via WebFetch on the date above);
quotes are short and attributed. Full texts live at the linked URLs —
nothing copyrighted is committed here.

---

## 1. RAG survey — Gao et al., "Retrieval-Augmented Generation for Large Language Models: A Survey"

- **Provenance:** https://arxiv.org/abs/2312.10997 (v5, Mar 2024; fetched 2026-11-15)
- **Key findings:** RAG fixes hallucination, stale knowledge and
  untraceable reasoning by merging model knowledge with an external
  corpus. Taxonomy: **naive → advanced → modular** RAG. Advanced RAG =
  pre-retrieval query enhancement + retrieval optimization +
  post-retrieval reranking; modular RAG composes these as swap-in modules.
  Provides an evaluation framework and benchmarks.
- **Relevance here:** our pipeline is already *advanced-RAG shaped*
  (hybrid retrieval, lexical rerank, verification); the modular stage
  (swappable embedder/reranker via the generation registry) is exactly
  the V5 architecture. The survey validates the roadmap order: fix
  retrieval measurement before adding components.

## 2. Positional bias — Liu et al., "Lost in the Middle: How Language Models Use Long Contexts"

- **Provenance:** https://arxiv.org/abs/2307.03172 (fetched 2026-11-15)
- **Key findings:** Accuracy is U-shaped in position — models use the
  **beginning and end** of the context best and degrade in the middle,
  even for long-context models. Implication: retrieve **fewer,
  higher-precision** passages and place the most relevant **first**.
- **Relevance here:** our context assembly is top-3 with lexical rerank
  ordering — small and deliberately ordered, which is the paper's own
  recommendation. It is also a standing argument **against** widening
  `top_k`: more context would bury the best chunk in the middle.

## 3. Dense retrieval — Karpukhin et al., "Dense Passage Retrieval for Open-Domain Question Answering"

- **Provenance:** https://arxiv.org/abs/2004.04906 (fetched 2026-11-15)
- **Key findings:** A dual-encoder trained on question–passage pairs beats
  Lucene-BM25 by 9–19% absolute top-20 accuracy. The ingredient is
  **supervised contrastive training**, not model size. Dense retrieval is
  a strong standalone signal — *when the encoder was trained for the
  domain*.
- **Relevance here:** the reason the neural-embedder gate exists. Our
  default `hash-ngram-local` embedder is an untrained stand-in; DPR's
  result is exactly the expected gain we forfeit until a real embedder is
  selected through the pre-registered benchmark with human-reviewed
  labels (`BLOCKED_OWNER_DATA`).

## 4. Evaluation — Es et al., "RAGAS: Automated Evaluation of Retrieval Augmented Generation"

- **Provenance:** https://arxiv.org/abs/2309.15217 (fetched 2026-11-15)
- **Key findings:** Reference-free RAG evaluation across three
  dimensions — retrieval quality, **faithfulness** (does the answer
  exploit the passages faithfully), and generation quality. Removing the
  ground-truth-annotation bottleneck enables fast evaluation cycles.
- **Relevance here:** our grounding gate + citation check are
  deterministic faithfulness proxies; the V5 verification
  off/shadow/enforce ladder is the calibrated path toward RAGAS-style
  faithfulness scoring, with enforce blocked on human-reviewed
  calibration data — the same dependency RAGAS-style metrics have on
  adjudicated examples.

## 5. Fusion — Cormack, Clarke & Buettcher, "Reciprocal Rank Fusion outperforms Condorcet and simple Rank Fusion Methods" (SIGIR 2009)

- **Provenance:** paper PDF (uwaterloo.ca; https→http redirect loop
  prevented full-text fetch — summary via docs.pinecone.io/guides/search/hybrid-search,
  fetched 2026-11-15); formula as stated in the original paper.
- **Key findings:** `score(d) = Σ 1/(k + rank_i(d))` over each ranked
  list; **k = 60** softens rank differences so one list's #1 cannot
  dominate. RRF needs **no score normalization** (BM25 and cosine live on
  incomparable scales), has no mixing weight to tune, and rewards
  documents that both lists agree on.
- **Relevance here:** `HybridIndex` fuses BM25 ∥ vector with RRF k=60 —
  the field-standard constant, chosen here independently and now
  documented against the source. Any move to weighted fusion would need
  the benchmark protocol; RRF's no-tuning property is why it stays.

## 6. Vector store — pgvector (v0.8.7) capability notes

- **Provenance:** https://github.com/pgvector/pgvector (README, fetched 2026-11-15)
- **Key findings:** `vector` up to 16k dims; `<=>` cosine distance;
  HNSW (better recall/speed, higher memory, buildable before data) vs
  IVFFlat (cheap build, needs data first, rows/1000 lists). **Exact
  search is the default and gives perfect recall**; on small tables a
  sequential scan can beat an index; index use requires ORDER BY on the
  bare operator + LIMIT.
- **Relevance here:** our V5 store uses **exact** `<=>` search — at 847
  chunks that is the correct choice (perfect recall, no ANN recall tax);
  HNSW becomes worth benchmarking only at a scale where sequential scan
  latency matters. The `vector(384)` fixed dimension and generation-bound
  rows match the manifest-breaking embedder contract.
