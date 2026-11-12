# Retrieval Engine V2 — design (Phase 2, P1)

Date: 2026-11-13 · Status: approved-by-owner-instruction (autonomous execution mandate) ·
Owner: engineering lead (AI/retrieval) · Target flow + component table supplied by the owner
(the two reference images; requirements quoted below).

## Intent and why

Upgrade the retrieval system to the fully-working **multilingual semantic RAG flow** the owner
specified, over the engine the repository already serves:

```
Student Question → Query Analysis → BM25 ∥ Dense → RRF → Candidate Pool
→ Cross-Encoder Reranker → Top Relevant Evidence → Parent/Neighbor Expansion → Grounding Gate
```

with the owner's explicit requirement: **candidate pool and top-K are benchmark-swept, not
fixed assumptions.**

## What already exists (measured, 2026-11-13)

The master spec's pipeline is largely built — the modules literally carry "RAG v2" docstrings:

| Target stage | State | Where |
|---|---|---|
| Query Analysis | ✅ | `retrieval/query_analysis.py` (content terms, IDF weights, rewrite), `normalize.py`, `transliteration.py`, `nctb/bijoy.py` — Bangla/Banglish/English/typo/mixed handling is first-class and tested |
| BM25 Search | ✅ | `retrieval/bm25.py` (class/subject/chapter filters) |
| Dense Search | ✅ | `retrieval/vector.py` + pluggable `Embedder` (HashingEmbedder hermetic default; remote model via `EMBEDDING_MODEL`+endpoint; manifest identity enforced) |
| RRF | ✅ | `retrieval/fusion.py` (k=60, deterministic tie-break), wired in `hybrid_index.py` |
| Candidate Pool | ✅ | `top_k × rag_candidate_factor` (knob exists) |
| Cross-Encoder Reranker | ❌ | only the deterministic lexical feature ranker exists; the `Reranker` seam is documented as *"a model-based reranker replaces exactly one stage of this pipeline when one is benchmarked"* |
| Top Relevant Evidence | ✅ | `context.assemble_evidence` (768-token selection budget, text dedupe, rank order) — **top_k=3 assembly is a LOCKED grounding-gate contract** |
| Parent / Neighbor Expansion | ❌ | absent; chunker emits chapter-level `parent_id` (dropped at serve time); sections/pages ride `CurriculumMeta` |
| Grounding Gate | ✅ | `services/tutor.py::_coverage_details` — **LOCKED** (IDF coverage ≥ 0.5, <2 absent terms, bigram guard) |
| Metadata filtering (class, subject, book, year, chapter) | ◐ | class/subject/chapter filter per lane; `book`/`curriculum_year` exist in `CurriculumMeta` but are not wired as filters |
| Deduplication (content hash + source-aware identity) | ◐ | ingest-time dedupe by `(content_hash, class_level)` with `shared_sources` merge exists in `nctb_loader.py`; assembly dedupes by normalized text; no candidate-pool dedup |
| Benchmark sweep of pool/top-K | ❌ | knobs exist (`rag_rrf_k`, `rag_candidate_factor`); no sweep harness; `evaluate_nctb_retrieval.py` already measures Recall@1/@5, MRR, Wilson CIs, paired bootstrap, and has `--ablation` |

The real NCTB corpus is present on this machine (`data/nctb/normalized/`, gitignored), so sweeps
can run against the served corpus, not only the 78-chunk sample.

## Locked invariants (will not move)

1. Grounding gate thresholds (coverage ≥ 0.5, absent budget 2, bigram guard) — never lowered.
2. Context assembly `top_k = 3` and the 768-token selection budget. The owner's "top-K must be
   swept" requirement is honored by sweeping the **candidate-pool depths and fusion/rerank
   stages** (the parts the flow diagram names); the final evidence count is the measured
   grounding contract — if the sweep shows a better final top-K, that is **reported as a
   recommendation** requiring the owner's reviewed baseline act, not changed here.
3. Prompt identity, injection wrapping, redaction, budget gate — untouched.
4. Hermetic CI: no network, no secrets, no new heavy dependencies. The deterministic default
   stack must keep serving tests and CI exactly as today.
5. Manifest law: changing the active embedder is a manifest-breaking event (operator act).
   This upgrade changes **nothing** about the default embedder.

## Approaches considered

**A. Big-bang replace** — rewrite `hybrid_index.py` around the new stages in one pass.
Rejected: the repo's ratchet is "never break what is measured"; the eval gate compares strictly
against the identity-bound baseline now; a single sweeping diff cannot attribute a metric
movement to a stage.

**B. Stage-by-stage, seams-first, defaults-preserving (chosen)** — each new stage enters as a
pluggable seam with config-gated activation, default behavior byte-identical to today, each
stage landed with tests and the eval battery, and one sweep harness producing the
evidence the owner asked for. Metric movement is attributable per stage; the gate decides.

**C. External retrieval service (pgvector/TEI stack now)** — rejected for this phase: the owner
table says *initially exact search; growth হলে pgvector*, and CI is hermetic. The interfaces are
built so pgvector/TEI become drop-in backend choices later without touching the flow.

## The design (approach B)

### 1. Cross-encoder reranker — pluggable stage

`retrieval/reranker.py`:

- `build_reranker(settings) -> Reranker` (the existing callable seam) with
  `RAG_RERANKER = "lexical" | "cross_encoder"` (default `"lexical"` = today's ranker, byte-identical).
- `"cross_encoder"` speaks a standard rerank HTTP contract (Cohere/TEI-shaped
  `POST {endpoint}/rerank` with `{model, query, documents}` → `results[{index, relevance_score}]`),
  OpenAI-compatible-key pattern reused; `httpx` (already a dependency) + the existing circuit
  breaker + timeouts; **graceful degradation**: on timeout/error the stage logs, meters
  (`RAG_LANE_LATENCY_SECONDS{lane="cross_encoder"}`, a fallback counter) and falls back to the
  lexical scores for that turn — degrade, never lie, never refuse for reranker reasons.
- Config validation at boot: `cross_encoder` without an endpoint is a configuration error
  (same doctrine as `embedding_model` without a backend).
- Model name rides the request (`RAG_RERANKER_MODEL`), operator-chosen (multilingual rerankers,
  e.g. bge-reranker-v2-m3 family, are endpoint-side decisions). No new Python dependencies.
- Documents sent to the reranker endpoint are **evidence text going to a third party** → passes
  through the same redaction discipline as LLM egress (`services/pii.py`), metered.

### 2. Parent / neighbor expansion — config-gated, default OFF

`retrieval/expansion.py` + wiring in the tutor's `_retrieve_and_gate` between top-evidence
selection and the gate:

- `RAG_NEIGHBOR_EXPANSION = false` (default; **default behavior is byte-identical**).
- When ON: for each selected hit, pull adjacent chunks from the same `(source, class_level,
  chapter, section)` ordered by `(page, id)` — one predecessor, one successor — plus the
  chapter-title context line for the parent signal (the chunker's chapter-level parent id is
  not a served object; propagating it is an ingestion/manifest change, deliberately deferred
  and documented).
- Expansion results: deduped against the selected evidence, inserted AFTER the hit they
  belong to, marked in trace/params (`expanded: true`), subject to the same 768-token
  selection budget and the same gate. No threshold moves; the sweep + eval battery measure
  the effect, and the refusal-rate delta is reported.
- Class scoping is absolute: a class-6 student never receives another class's chunk.

### 3. Candidate-pool deduplication — content hash + source-aware identity

In `hybrid_index.search` after fusion, before rerank: collapse candidates whose
normalized indexable text is identical AND whose `meta.source` matches (same-book duplicate
rows), keeping the best fused rank; cross-class copies stay distinct by design (class-scoped
provenance is a product contract). Measured via the eval battery; expected neutral-to-positive.

### 4. Metadata filtering — book and year

Optional `book: str | None`, `year: int | None` parameters through `HybridIndex.search` → both
lanes (exact match on `meta.book` / `meta.curriculum_year` when provided). No-op on today's
call sites and the sample corpus; tests with synthetic chunks prove the filter.

### 5. Benchmark sweep — the owner's explicit requirement

`scripts/benchmark_retrieval_v2.py` (hermetic on the sample corpus; the same grid runnable
against the real corpus via the existing `--corpus`-style flags of `evaluate_nctb_retrieval.py`):

- Grid: `candidate_factor ∈ {2,3,4,6}`, `rrf_k ∈ {20,60,100}`, reranker ∈ {lexical,
  cross-encoder when configured}, neighbor expansion ∈ {off, on}.
- Metrics per cell: Recall@1/@5, MRR, gate-pass rate on family-C (refusal correctness),
  p50/p95 stage latencies — Wilson CIs throughout, reusing `evaluation.stats`.
- Output: JSON + a markdown table committed next to the report; the sweep **recommends**
  knob values with the measured deltas. Default knobs stay as-is unless the sweep shows a
  win at or above noise bounds; any change to the locked final top-K is reported, not made.

### 6. Embedder benchmark mode + a measured audit fix

- `evaluate_nctb_retrieval.py`/sweep gain an embedder-comparison mode so "benchmarked
  multilingual embedding model" is a runnable, evidence-producing procedure for the operator
  (local hash vs any configured remote endpoint), keeping the manifest law.
- Audit fix F-3: `RemoteEmbedder` verifies its dimension against the corpus manifest **after
  the first embed call** (today the dim comparison is dead in the remote lane).

## Testing and gates (SWE SOP)

TDD per stage; new modules get coverage-floor entries (additive ratchet); the full battery
after every stage and at the end: eval CLI vs the identity-bound baseline, golden 0.9 gate,
redteam, `evaluate_nctb_retrieval` (recall/MRR, real corpus where available),
injection/safety suites, `test_bangla_matrix`, coverage floors, ruff/mypy/lint-imports.
The refusal-rate delta is reported explicitly. No baseline regeneration in the same PR.

## Non-goals

pgvector (growth-path only), a real default embedding model (operator decision),
corpus changes, prompt changes, gateway/threshold changes.
