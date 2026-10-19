# Retrieval variants, diversity and the reranker (A4-01, A4-02, A4-07, A4-08)

Commands (from `apps/api`):

```bash
python -m bangla_gpt_api.evaluation.cli --variant-matrix --out eval/tmp/variant_matrix.json
python scripts/evaluate_nctb_retrieval.py                # real corpus, --out to redirect
python scripts/ablate_nctb_chunking.py                   # size/overlap/diversity, real pages
```

Artifacts: `apps/api/eval/variant_matrix.json` (held-out golden split),
`data/nctb/retrieval_eval.json` (real-corpus families), `data/nctb/chunk_ablation.json`
(size/overlap/diversity). Code: `evaluation/variant_matrix.py`,
`apps/api/scripts/evaluate_nctb_retrieval.py`, `apps/api/scripts/ablate_nctb_chunking.py` (both run from `apps/api`).
Tests: `tests/test_eval3_variant_matrix.py`, `tests/test_evaluate_nctb_retrieval.py`.

## Chunk size, overlap and strategy ablation (A3-02)

Command: `cd apps/api && python scripts/ablate_nctb_chunking.py` (re-chunks the
same extracted pages under each configuration, so the comparison is a
comparison). Artifact: `data/nctb/chunk_ablation.json`; seed 20260825; same
family A (self-sentence) / family B (chapter-title) queries per row.

| Configuration | served chunks | build s | A recall@1 | A recall@3 | A recall@5 | A recall@10 | A MRR | B recall@1 | B recall@5 | B MRR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| target-160 | 1 785 | 49.3 | 0.750 | 1.000 | 1.000 | 1.000 | 0.8667 | 0.500 | 0.925 | 0.6720 |
| **target-220 (served)** | **1 390** | **33.8** | 0.750 | 0.9167 | 0.9667 | 0.9833 | 0.8446 | 0.475 | 1.000 | 0.6854 |
| target-320 | 1 061 | 23.3 | **0.8667** | 0.950 | 1.000 | 1.000 | **0.9136** | **0.550** | 0.950 | **0.7138** |
| target-220 + 40-word overlap | 1 640 | 23.5 | 0.7167 | 0.9833 | 0.9833 | 1.000 | 0.8417 | 0.500 | 1.000 | 0.6717 |
| 220, rerank-off (reference) | 1 390 | 33.8 | 0.750 | 0.9167 | 0.9667 | 0.9833 | 0.8450 | 0.475 | 1.000 | 0.6854 |
| 220, lexical lane (reference) | 1 390 | 33.8 | 0.750 | 0.9167 | 0.9667 | 0.9833 | 0.8450 | 0.475 | 1.000 | 0.6854 |
| 220 + MMR diversity | 1 390 | 33.8 | 0.750 | **0.9333** | 0.9667 | 0.9833 | 0.8460 | 0.475 | 1.000 | 0.6854 |

Reading it:

- **320 words wins on this corpus** (A recall@1 0.8667 vs 0.750; B recall@1
  0.55 vs 0.475; fewer chunks, faster build). The served 220 was chosen on
  the *earlier* corpus revision; this table is the evidence that the choice
  should be revisited — a size change is a retrieval change gated by the
  pre-registered tolerance, so it is recorded here for that decision rather
  than flipped in this pass.
- **40-word overlap loses on precision** (A recall@1 0.7167 vs 0.750 for the
  same target) while adding 250 chunks: the served 0-word default is the
  measured choice.
- **The reranker buys nothing in these families** on the real corpus (rank
  identical to lexical) — its measured gain lives on the golden split
  (+1.65 pp Recall@1, below).
- **MMR** helps A recall@3 (0.9167 → 0.9333) at no cost in this family and is
  off by default (see the diversity section below).

## Variant baselines on the held-out split (A4-01)

Frozen `test` split, filtered lane (class+subject pre-filter — the tutor's
lane), seed 20261019, top-k 10, 181 positive items, gold units resolved from
the corpus (0 unmatched). Every metric carries a seeded 95% percentile
bootstrap CI; latency is wall-clock on the measuring host and must only be
compared inside one run.

| Variant | Recall@1 (CI95) | Recall@3 | Recall@5 (CI95) | Recall@10 | MRR@10 (CI95) | nDCG@10 | p50 ms | p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lexical (BM25 + Bangla analysis) | 0.9006 (0.856-0.939) | 0.9945 | 1.0 (1.0-1.0) | 1.0 | 0.9461 (0.920-0.969) | 0.9600 | 1.04 | 3.76 |
| dense (hashing stand-in) | 0.8840 (0.834-0.928) | 0.9945 | 0.9945 (0.983-1.0) | 1.0 | 0.9365 (0.909-0.960) | 0.9528 | 1.85 | 6.28 |
| hybrid, rerank off (RRF only) | 0.9006 (0.856-0.939) | 0.9945 | 1.0 (1.0-1.0) | 1.0 | 0.9461 (0.920-0.969) | 0.9600 | 4.38 | 12.35 |
| **hybrid, served** | **0.9171 (0.879-0.956)** | 1.0 | 1.0 (1.0-1.0) | 1.0 | **0.9549 (0.931-0.976)** | 0.9665 | 10.19 | 24.93 |
| hybrid + MMR diversity (λ=0.7) | 0.9171 (0.879-0.956) | 1.0 | 1.0 (1.0-1.0) | 1.0 | 0.9549 (0.931-0.976) | 0.9665 | 13.13 | 33.56 |

Paired MDE against the served lane (the smallest difference this sample can
resolve at 95% CI / 80% power): 0.0 for lexical, rerank-off and MMR — the
split's Recall@5 is saturated at 1.0, so a Recall@5 comparison cannot fail
here. `hybrid_served_vs_dense` is 0.0155, which is the resolution the dense
lane's ceiling actually needs. The honest reading: this corpus can rank the
lanes on **Recall@1** (0.9171 served vs 0.9006 lexical vs 0.8840 dense) but
not on Recall@5; the real-corpus families in `data/nctb/retrieval_eval.json`
are the measurement with headroom.

### The real corpus (same command, `data/nctb/retrieval_eval.json`, 2026-10-19)

n = 100 self-sentence (A), 80 chapter-title (B), 100 romanised (D), 1390
served chunks, seed 20260825, top-k 10, 1000 bootstrap resamples:

| Variant | A recall@1 | A nDCG@10 | B recall@1 | D recall@1 (Banglish) |
| --- | --- | --- | --- | --- |
| lexical | 0.78 | 0.8946 | 1.0 | 0.52 |
| dense (hashing stand-in) | 0.34 | 0.4788 | 0.8625 | 0.00 |
| hybrid, rerank off | 0.78 | 0.8946 | 1.0 | 0.52 |
| hybrid, served | 0.78 | 0.8942 | 1.0 | 0.52 |

Serviced hybrid: A recall@1/@3/@5/@10 = 0.78 / 0.93 / 0.97 / 0.99,
nDCG@10 0.8942 (CI95 0.854-0.935), MRR 0.8624; B 1.0 across the board;
D 0.52 / 0.75 / 0.86 / 0.92, nDCG@10 0.7191.

Two findings this table makes unavoidable, and neither is papered over:

1. **The dense lane is the weak lane** (A recall@1 0.34, D recall@1 0.00):
   the hashing stand-in is a phonetic-variant lane, not semantic retrieval.
   On the real corpus the served hybrid equals the lexical lane on A/B/D,
   i.e. the vector lane currently adds latency (p50 613 ms vs 65 ms) without
   adding recall in these families. That is the measured case for the
   embedding-model work (A4-02), and the reason the ADR is an owner decision
   rather than a claim.
2. **The reranker's measurable gain on the golden split is +1.65 points of
   Recall@1** (0.9171 served vs 0.9006 rerank-off). On the real corpus the
   two are identical on these families. Its cost is +5.8 ms p50 on the
   sample corpus and nothing per call (no model, no tokens).

### Lexical blind spots (A4-02's "quantify what lexical retrieval misses first")

- **Banglish**: family D is family A romanised, queried against the same
  chunks. Served recall@5: Bangla **0.97** vs Banglish **0.86** — a paired
  delta of **−0.11**, CI95 [−0.18, −0.05] over 100 chunk pairs (euqal-weight
  mean of paired differences; the roman lane's cost is real and resolvable).
  Per-query script labels from the shipped detector: family A 99 bangla + 1
  mixed; family D 25 banglish + 75 mixed (the detector requires a roman-lane
  corpus hit, and the mixed label is honest for romanised text carrying
  ASCII numerals).
- **Paraphrase/synonyms**: not separable on this corpus — the golden set's
  strata are contextual (576) and definition (48) over a 78-chunk sample
  where lexical recall@5 is already 1.0. A paraphrase-sensitive subset needs
  the real-corpus golden set, which is owner-scoped dataset work; the
  variant report will show it the moment that set exists (the `stratum` key
  is already the grouping dimension).
- **Vector-only contributions**: `variants.vector` above is the measured
  lane; its A recall@1 of 0.34 against lexical 0.78 is the size of the gap a
  dense model would have to close before it earns its latency.

## Diversity / dedup and the top-k decision (A4-07)

- **MMR** (`retrieval/diversity.py`, λ=0.7) is opt-in. On the golden split it
  changes nothing (identical metrics, +2.9 ms p50). On the real-corpus
  ablation (`data/nctb/chunk_ablation.json`, same pages, target-220 row) the
  diversity stage moves family A recall@3 0.9167 → 0.9333 and MRR 0.8446 →
  0.8460 with no row regressing; family B is unchanged. It is therefore *not*
  on in the served path: the sample corpus the golden set is built on carries
  no near-duplicate candidates, and "used only where metrics improve" is
  satisfied by leaving it off where it does not. Turning it on is a config
  change (`diversify=True`) whose cost is the +2.9 ms above.
- **Top-k from the recall-versus-context-cost curve** (served lane, held-out
  split, measured): k=1 → recall 0.9171 at 130 chars (32 est. tokens);
  k=2 → 0.9779 at 262 chars; **k=3 → 1.0 at 398 chars (98 tokens)**;
  k=10 → 1.0 at 957 chars (236 tokens). The served `top_k=3` is the smallest
  k that reaches the recall ceiling, at 42% of the k=10 context cost. The
  full curve is in `eval/variant_matrix.json` under `top_k_curve`.
- **Load-time dedup** is enforced regardless: `serve_stats` records
  `duplicates_dropped_at_load: 1026` and `served_duplicate_class_text_pairs:
  0` (a non-zero value there is a regression, pinned by the retrieval-eval
  tests).

## The reranker (A4-08)

The shipped reranker is deterministic and local: coverage, proximity and
trigram features over the fused candidates (`retrieval/hybrid_index.py`). It
has no per-call cost, no model and no token limit exposure, and its latency is
the difference between the `hybrid_rerank_off` and `hybrid_served` rows above
(+5.8 ms p50 on the sample corpus).

- **Measured gain**: +1.65 pp Recall@1 on the held-out split (0.9006 →
  0.9171; the paired MDE for Recall@5 is 0.0 because the split saturates, so
  the Recall@1 column is the honest reading).
- **Fallback when unavailable**: the fusion-only ranking (`rrf_only_rerank`,
  the `hybrid_rerank_off` variant). `tests/test_eval3_retrieval_ops.py`
  injects a reranker that raises and pins both halves: the fault is loud
  (the exception propagates — no silent wrong answers) and the documented
  fallback ranking still answers, ordered, over the same candidates. Wiring
  the fallback into `HybridIndex` itself is a one-line change owned by the
  retrieval module (`reranker=FallbackReranker(make_lexical_rerank(...))`);
  the eval-side artifact quantifies what that fallback costs.
- **Long-query behaviour**: a ~16k-character Bangla query is exercised by the
  same test file; the local ranker sees the whole query and the response is
  bounded to top-k — there is no provider token limit to exceed on this path.

## Caches (A4-09)

`CachedRankingIndex` keys on `sha256(query | tenant_id | class | subject |
chapter | top_k | min_score)` prefixed with the index version (corpus
fingerprint, or an explicit index-version name). `tests/test_rag2_cache_scope.py`
pins the dimensions and the invalidation; `tests/test_eval3_retrieval_ops.py`
adds the end-to-end version: two **real** BM25 indexes over different corpora
produce different fingerprints, the rebuilt index serves its own passage, and
the old key space can only ever return old-corpus chunks. A tenant dimension
exists in the key and is passed to tenant-aware inner indexes; the corpus
itself is single-tenant in this build.
