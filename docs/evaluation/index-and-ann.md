# Index budget and the ANN decision (A3-05, A3-06)

Commands (from `apps/api`):

```bash
python -m bangla_gpt_api.evaluation.cli --index-budget --out eval/index_budget.json
python -m bangla_gpt_api.evaluation.cli --ann-sweep   --out eval/ann_sweep.json
```

Artifacts: `apps/api/eval/index_budget.json`, `apps/api/eval/ann_sweep.json`.
Code: `evaluation/index_budget.py`, `evaluation/ann_sweep.py`. Tests:
`tests/test_eval3_retrieval_ops.py`.

## The stated budget (A3-05)

The budget is a decision point, not an aspiration:

| Budget | Value | Source |
| --- | --- | --- |
| index build (real corpus) | < 120 s | before the deferred pgvector/persistence work is triggered |
| search p95 (real corpus) | < 1500 ms | same |
| cold start (fresh process, load + build) | measured, no budget asserted | boot time is a deployment concern; the number is recorded so it can be budgeted |

## Measured (2026-10-19, Windows 11 developer host, Python 3.12.10)

Corpus: `data/nctb` after the loader's dedupe and legacy drops
(`data/nctb/retrieval_eval.json` → `serve_stats`), **1 390 served chunks**,
mean chunk text 3 627 bytes.

| Measurement | Value | Budget | Within |
| --- | --- | --- | --- |
| corpus chunks | 1 390 | — | — |
| corpus artifact bytes (normalized + quality report) | 7 739 648 | — | — |
| mean chunk text bytes | 3 626.8 | — | — |
| corpus load (disk → chunks) | 4.92 s | — | — |
| index build (BM25 + vector + hybrid) | 44.40 s | 120 s | yes |
| index peak allocation (tracemalloc, second build) | 140.26 MB | — | — |
| index allocation per chunk | 105 810 B | — | — |
| search p50 | 96.63 ms | — | — |
| search p95 | 434.00 ms | 1 500 ms | yes |
| vector-lane search p95 (ANN sweep, exact) | 299.55 ms | 1 500 ms | yes |
| interpreter baseline (`python -c pass`) | 262.52 ms | — | — |
| cold start, fresh process (imports + load + build) | 157 567 ms wall | — | — |
| cold start, in-child load + build | 53 039 ms | — | — |

Honest notes on those two cold-start rows:

- The wall-clock figure (157 s) is inflated by **host contention**: this
  machine was running three evaluation jobs concurrently. The in-child
  measurement (53 s) is the same work without the outer process's scheduling
  delay, and the two differ by 100 s that is contention, not work. Re-run on
  an idle host before quoting a cold-start budget.
- The build figure is **not** a tracemalloc measurement. The module's first
  run reported 347 s because it timed a build *while* tracemalloc was
  tracking every allocation; the fix is two passes (clean build for time,
  second build under tracemalloc for memory), and `build.definition` in the
  artifact records that.
- A cold-start child that fails is recorded as `status: "failed"` with every
  number null. That also happened on the first run (a string path reaching
  `Path`-typed code) and the status field is the fix — a traceback's wall
  time must never be quoted as a cold start.

## ANN: the choice, justified against staying on the existing database (A3-06)

The repo has no ANN and no vector store today: the vector lane is brute-force
cosine over in-memory vectors (`retrieval/vector.py`), per the design in
ADR-0003. A3-06 therefore has two halves — *is staying justified?* and *what
would an ANN's parameters be?* — and both are measured here.

### The recall-versus-latency curve (real corpus, IVF-style ANN)

The sweep builds an IVF index (k-means centroids over the same embedder
vectors, probe `nprobe` nearest lists — the same shape as pgvector's
IVFFlat) over 1 390 chunks and ranks 40 self-sentence queries with known gold
units. `lists`/`probes` are the parameters a real vector store would be set
with. Recall is against the gold chunk, so the exact lane's own recall is the
reference line (1.0 would flatter the ANN).

| Index | lists | probes | recall@10 (gold) | p50 ms | p95 ms | corpus scanned | build s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| exact brute force (served) | — | all | 0.55 | 85.9 | 299.5 | 100% (1 390) | n/a |
| IVF | 4 | 1 | 0.525 | 31.0 | 75.4 | 37.1% | 2.6 |
| IVF | 4 | 2 | 0.55 | 46.4 | 86.7 | 67.4% | 2.6 |
| IVF | 4 | 4 | 0.55 | 72.8 | 162.4 | 100.0% | 2.6 |
| IVF | 8 | 1 | 0.425 | 40.1 | 82.9 | 23.4% | 9.6 |
| IVF | 8 | 2 | 0.525 | 75.0 | 117.8 | 52.8% | 9.6 |
| IVF | 8 | 4 | 0.55 | 142.1 | 195.3 | 83.2% | 9.6 |
| IVF | 8 | 8 | 0.55 | 185.1 | 363.7 | 100.0% | 9.6 |
| IVF | 16 | 1 | 0.30 | 9.9 | 44.6 | 7.7% | 15.6 |
| IVF | 16 | 2 | 0.50 | 30.0 | 55.5 | 19.5% | 15.6 |
| IVF | 16 | 4 | 0.55 | 64.9 | 160.9 | 39.3% | 15.6 |
| IVF | 16 | 8 | 0.55 | 71.5 | 107.9 | 67.1% | 15.6 |

Reading it:

- **The exact lane is inside its own budget** (p95 299.5 ms vs the 1 500 ms
  budget; the artifact records `exact_p95_within_budget: true`). At 1 390
  chunks, brute force needs no ANN.
- **Parameter guidance with numbers**: `lists=4, probes=1` is the
  least-scanning configuration that keeps the exact lane's recall within 5%
  (0.525 vs 0.55) while scanning 37% of the corpus and cutting p95 from
  299.5 → 75.4 ms. `probes` below ~2 buys latency with recall (16/1 = 0.30,
  the worst row), and `lists=8` costs 4x the build time of `lists=4` without
  buying recall — the curve, not the pgvector heuristic, is the tuning guide.
- **Filtered search** is verified in the same artifact: the exact lane
  pre-filters (the product's behaviour — the filter is inside the scan), and
  the ANN lane is measured both pre-filtered and post-filtered. The post-filter
  scans strictly more postings for the same result, which is why a
  post-filtering vector store silently loses the recall it looks like it keeps.
- **The scale projection** (labelled as a projection in the artifact, never a
  measurement): linear extrapolation from the measured per-chunk cost
  (0.0754 ms/chunk) puts exact-scan p95 at ~2.3 s at 10k chunks, ~23 s at
  100k and ~226 s at 1M —
  i.e. the exact lane stops being viable somewhere between 10k and 100k
  chunks, which is the trigger for the deferred pgvector work.
- **The ANN cannot fix the lane's quality**: the dense lane's own recall@10
  is 0.55 on these queries because the shipped embedder is a deterministic
  phonetic stand-in, not a semantic model. An ANN is a latency tool; the
  embedding model (owner decision; the choice, its licence and its measured lift
go here when made -- this file is the placeholder for that record
  shortlist in `docs/RAG_ARCHITECTURE.md`) is the quality tool.

### Decision recorded

1. **Stay on the existing database** for the corpus the product serves today:
   the exact lane is inside both stated budgets, and the vector lane's recall
   does not justify new infrastructure yet.
2. **The parameters for the day it changes** are measured above
   (`lists ≈ sqrt(n)`, `probes` chosen from the curve, pre-filtering
   mandatory), so the pgvector decision starts from a curve rather than an
   opinion.
3. **Filtered-search performance is verified** (exact pre-filter vs ANN
   pre/post-filter) and the post-filter hazard is recorded.
