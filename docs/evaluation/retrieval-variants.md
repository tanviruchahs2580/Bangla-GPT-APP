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

## Chunk size, overlap and strategy ablation (A3-02, re-run for A3-01)

Command: `cd apps/api && python scripts/ablate_nctb_chunking.py` (re-chunks the
same extracted pages under each configuration, so the comparison is a
comparison). Artifact: `data/nctb/chunk_ablation.json`; seed 20260825; same
family A (self-sentence) / family B (chapter-title) queries per row. Rows from
2026-10-20, after A3-01 moved the served sizing from words to tokens measured
with the configured `TokenCounter` (612 tokens = 220 words at the measured
2.7812 tokens/word; `docs/NCTB_DATA_PIPELINE.md` §5).

| Configuration | served chunks | build s | A recall@1 | A recall@3 | A recall@5 | A recall@10 | A MRR | B recall@1 | B recall@5 | B MRR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 160 words | 1 979 | 11.6 | 0.85 | 1 | 1 | 1 | 0.9167 | 0.275 | 0.75 | 0.4975 |
| 220 words (pre-wave-5 served) | 1 523 | 10.9 | 0.8667 | 0.9833 | 1 | 1 | 0.92 | 0.25 | 0.95 | 0.558 |
| 320 words | 1 102 | 11.1 | 0.8667 | 0.9833 | 1 | 1 | 0.9236 | 0.35 | 1 | 0.6088 |
| 220 words + 40-word overlap | 1 778 | 13.0 | 0.6333 | 1 | 1 | 1 | 0.8111 | 0.25 | 0.85 | 0.5072 |
| **612 tokens (served, A3-01)** | **1 565** | **10.9** | **0.7833** | **0.9833** | **0.9833** | **1** | **0.8799** | **0.375** | **0.95** | **0.6036** |
| 420 tokens | 2 113 | 11.4 | 0.8333 | 0.9833 | 0.9833 | 1 | 0.9056 | 0.325 | 0.875 | 0.5728 |
| 820 tokens | 1 236 | 12.0 | 0.85 | 0.9833 | 1 | 1 | 0.9153 | 0.375 | 0.95 | 0.6058 |
| 612 tokens + 40-word overlap | 1 772 | 11.3 | 0.5833 | 0.9333 | 1 | 1 | 0.7631 | 0.275 | 0.85 | 0.5182 |
| 612 tokens + MMR diversity | 1 565 | 10.9 | 0.7833 | 0.9833 | 0.9833 | 1 | 0.8799 | 0.375 | 0.95 | 0.6036 |
| 612 tokens, lexical lane | 1 565 | 10.9 | 0.7667 | 0.9833 | 0.9833 | 1 | 0.8715 | 0.375 | 0.95 | 0.6011 |
| 220 words + MMR diversity | 1 523 | 10.9 | 0.8667 | 0.9833 | 1 | 1 | 0.92 | 0.25 | 0.95 | 0.5594 |
| 220 words, lexical lane | 1 523 | 10.9 | 0.8333 | 0.9833 | 1 | 1 | 0.9033 | 0.25 | 0.975 | 0.5532 |

**Deltas of the served configuration vs the word baseline**
(`deltas_vs_word_baseline` in the artifact): served chunks +42,
A recall@1 **−0.0834**, A recall@3 0.0, A recall@5 −0.0167, A MRR −0.0401,
B recall@1 **+0.125**, B recall@5 0.0, B MRR +0.0456.

Reading it:

- **The unit change is a trade, not a free win.** Deriving 612 tokens from the
  old 220 words kept the *size* (raw chunks 828 vs 816 on the same pages) but
  not the retrieval outcome: family A (self-sentence) recall@1 drops 8.3 pp
  while family B (chapter-title) gains 12.5 pp. Same queries, same pages — the
  difference is boundary placement.
- **The larger targets measure better on this corpus, within the sample's
  resolution**: 320 words, 420 tokens and 820 tokens measure A recall@1
  0.8667 / 0.8333 / 0.85 against 0.7833 at the served 612 (each query is 1.67
  pp at n=60, so 1-2 queries). The wave-5 record of this artifact read 0.900
  for all three; that reading does not reproduce one-for-one after the
  recovered chunker's 2-chunk difference in those rows, and the rebuild's
  numbers are recorded as measured rather than inherited. The direction —
  larger sizes rank better than the derived default, and 820 tokens also
  matches the best B recall@1 (0.375) — holds in both. As before, a size
  change is a retrieval change gated by the pre-registered tolerance, so it is
  recorded here for that decision rather than flipped in this pass; the A3-01
  default stays the derived 612 (no silent size change). Three of the eight
  configurations (320 words, 420 and 820 tokens) measure 2-10 chunks away from
  the wave-5 record on the same pages; the served configuration and every
  delta below reproduce exactly.
- **40-word overlap loses on precision** in both units (A recall@1 0.6333 at
  220 words, 0.5833 at 612 tokens) while adding ~250 chunks: the 0-word
  default stays.
- **The reranker buys nothing in these families** on the real corpus (lexical
  lane within 0.3-1.7 pp of the served rank) — its measured gain lives on the
  golden split (+1.65 pp Recall@1, below).
- **MMR** is neutral in these families at 612 tokens (identical ranks) and is
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

### The real corpus (same command, `data/nctb/retrieval_eval.json`, 2026-10-20)

n = 100 self-sentence (A), 80 chapter-title (B), 100 romanised (D), 1,565
served chunks, seed 20260825, top-k 10, 1000 bootstrap resamples:

| Variant | A recall@1 | A nDCG@10 | B recall@1 | D recall@1 (Banglish) |
| --- | --- | --- | --- | --- |
| lexical | 0.82 | 0.9278 | 0.65 | 0.57 |
| dense (hashing stand-in) | 0.36 | 0.5418 | 0.2625 | 0.01 |
| hybrid, rerank off | 0.82 | 0.9278 | 0.65 | 0.57 |
| hybrid, served | 0.84 | 0.9352 | 0.65 | 0.57 |

Served hybrid: A recall@1/@3/@5/@10 = 0.84 / 0.99 / 0.99 / 1.0, nDCG@10 0.9352
(CI95 0.906-0.964), MRR 0.9129; B 0.65 / 0.95 / 0.975 / 1.0, nDCG@10 0.8548,
MRR 0.8054; D 0.57 / 0.85 / 0.92 / 0.98, nDCG@10 0.7835, MRR 0.7191.

Two findings this table makes unavoidable, and neither is papered over:

1. **The dense lane is the weak lane** (A recall@1 0.36, D recall@1 0.01):
   the hashing stand-in is a phonetic-variant lane, not semantic retrieval.
   On the real corpus the served hybrid adds 2 pp on A over the lexical lane
   (0.84 vs 0.82) and equals it on B/D, at p50 136 ms against 19 ms — the
   vector lane's latency is paid for one family's 2 pp in these families.
   That is the measured case for the embedding-model work (A4-02), and the
   reason the ADR is an owner decision rather than a claim.
   **The real model is wired** (`retrieval/gemini_embedder.py`, 768 dims behind
   the same `Embedder` protocol, licence/limits in ADR-0003): the same command
   with `EMBEDDING_MODEL=gemini-embedding-001` swaps the lane, and the run
   resumes off `EMBEDDING_CACHE_PATH` after the free tier's daily 429 — the
   cache held 825 vectors after the 2026-10-21 attempt. Until a key with quota
   runs it to the end, the numbers above stay the hashing lane's.
2. **The reranker's measurable gain on the golden split is +1.65 points of
   Recall@1** (0.9171 served vs 0.9006 rerank-off). On the real corpus the
   two differ by that same 2 pp on family A and are identical on B/D. Its
   cost is +5.8 ms p50 on the sample corpus and nothing per call (no model,
   no tokens).

### Lexical blind spots (A4-02's "quantify what lexical retrieval misses first")

- **Banglish**: family D is family A romanised, queried against the same
  chunks. Served recall@5: Bangla **0.99** vs Banglish **0.92** — a paired
  delta of **−0.07**, CI95 [−0.13, −0.02] over 100 chunk pairs (equal-weight
  mean of paired differences; the roman lane's cost is real and resolvable).
  Per-query script labels from the shipped detector: family A 100 bangla;
  family D 26 banglish + 74 mixed (the detector requires a roman-lane corpus
  hit, and the mixed label is honest for romanised text carrying ASCII
  numerals).
- **Paraphrase/synonyms**: not separable on this corpus — the golden set's
  strata are contextual (576) and definition (48) over a 78-chunk sample
  where lexical recall@5 is already 1.0. A paraphrase-sensitive subset needs
  the real-corpus golden set, which is owner-scoped dataset work; the
  variant report will show it the moment that set exists (the `stratum` key
  is already the grouping dimension).
- **Vector-only contributions**: `variants.vector` above is the measured
  lane; its A recall@1 of 0.36 against lexical 0.82 is the size of the gap a
  dense model would have to close before it earns its latency.

## Diversity / dedup and the top-k decision (A4-07)

- **MMR** (`retrieval/diversity.py`, λ=0.7) is opt-in. On the golden split it
  changes nothing (identical metrics, +2.9 ms p50). On the real-corpus
  ablation (`data/nctb/chunk_ablation.json`, same pages, target-220 row) the
  diversity stage moves nothing in that row (A recall@3 1.0 → 1.0, MRR 0.9111
  → 0.9111; family B unchanged), and it moves nothing in the 612-token served
  row either. It is therefore *not*
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
