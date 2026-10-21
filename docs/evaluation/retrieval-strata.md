# Retrieval metrics per stratum (A8-03 / AUD-A2-12)

Command: `cd apps/api && python scripts/strata_report.py`. Artifact:
`apps/api/eval/strata_report.json` (committed, deterministic under the sample
corpus; seed, resample counts, corpus fingerprint and golden hashes are
recorded inside).

## What is measured

Every answerable item of `apps/api/eval/golden_v2.json` (624 of 646) is
retrieved twice against the served hybrid index:

- **filtered** — exactly what the tutor does: search pre-filtered by the
  item's class level and subject;
- **unfiltered** — the same query with no metadata filter, so the value of the
  pre-filter is visible instead of assumed.

Gold evidence is derived from the corpus, not from the retriever: an item's
gold unit is the chunk whose `(class_level, subject, section)` equals the
section the generator recorded. All 624 resolve (`gold_unmatched_items: 0`).

Metrics per stratum: Recall@1/3/5/10, MRR@10, nDCG@10 and hit-rate@10, each
with a seeded percentile 95% bootstrap CI; `mde_absolute` is the smallest
change that stratum's n can resolve at 95% confidence and 80% power for
Recall@5, with `mde_by_metric` for every metric and
`filtered_vs_unfiltered_mde` for the paired filter comparison.

## Measured on the committed artifact (2026-10-19, sample corpus)

| Stratum | n | Recall@1 (CI95) | Recall@5 (CI95) | MRR@10 | nDCG@10 | MDE abs. r@5 / r@1 |
| --- | --- | --- | --- | --- | --- | --- |
| all (filtered) | 624 | 0.9247 (0.9022-0.9439) | 1.0 (1.0-1.0) | 0.9607 | 0.9709 | 0.0 / 0.0296 |
| all (unfiltered) | 624 | 0.8125 (0.7821-0.8413) | 0.9856 | 0.8903 | 0.9162 | 0.0 / 0.0438 |
| class 6 (filtered) | 184 | 0.8913 (0.8424-0.9348) | 1.0 | 0.9420 | 0.9570 | 0.0 / 0.0645 |
| class 7 (filtered) | 80 | 0.9625 (0.9250-1.0) | 1.0 | 0.9792 | 0.9845 | 0.0 / 0.0599 |
| class 8 (filtered) | 112 | 0.9464 (0.8929-0.9821) | 1.0 | 0.9732 | 0.9802 | 0.0 / 0.0599 |
| class 9 (filtered) | 144 | 0.9444 (0.9028-0.9792) | 1.0 | 0.9711 | 0.9786 | 0.0 / 0.0537 |
| class 10 (filtered) | 104 | 0.9038 (0.8462-0.9519) | 1.0 | 0.9519 | 0.9645 | 0.0 / 0.0814 |

The table above is a hand copy for readers; the artifact is authoritative and
`apps/api/scripts/strata_report.py` prints the same block from the JSON, so a
regeneration refreshes both (a test asserts the artifact matches the committed
golden hashes).

## What the numbers say

1. **The class+subject pre-filter is worth about 11 points of Recall@1**
   (0.9247 filtered vs 0.8125 unfiltered) and the paired MDE for that
   comparison is 0.0134 — an order of magnitude below the effect, so this is a
   measured difference, not noise.
2. **Recall@5 is saturated on the sample corpus** (1.0 with the CI collapsed to
   [1.0, 1.0]); the artifact flags this as `mde_degenerate_ceiling: true`. The
   honest reading is that this corpus cannot gate Recall@5: use Recall@1, or
   the real-corpus families in `data/nctb/retrieval_eval.json`.
3. **Stratum size sets the resolution.** Class 7 (n=80) can resolve ~6 points
   of Recall@1; class 10 (n=104) ~8 points. A 2-point regression claim on a
   stratum of this size is below its MDE and should not be made.
4. Every stratum is saturated at Recall@5 on this corpus: the held-out `test`
   split's Recall@1 is 0.9171 over n=181 (MDE 0.0576) against dev's 0.9278 over
   n=443 (MDE 0.0345), and both are 1.0 at Recall@5. Subject strata: science
   0.9417 (n=360), mathematics 0.9120 (n=216), bangla 0.8542 (n=48).
5. The filtered lane missed the gold unit in no item at all
   (`error_analysis.filtered_misses_by_stratum` is empty), so there is no
   per-item error list to review on this corpus; the field exists for the
   strata that will have misses once a non-saturated corpus is measured.

## Limits and the honest gaps

- The golden set is defined over the bundled sample corpus, so the report is
  reproducible in CI. Running it with `--corpus-dir ../../data/nctb` leaves
  every gold unit unmatched (181 of 181 on the test split, verified
  2026-10-19): a real-corpus stratum report needs a golden set built from that
  corpus, which is owner-scoped dataset work.
- Negative (must-refuse) items are not retrieval metrics; their abstention
  behaviour is reported in `generation-metrics.md`.
- Per-stratum CIs use 250 resamples (`STRATA_RESAMPLES`) instead of 1000: the
  full report holds ~25 strata x 2 lanes x 7 metrics and 1000 resamples cost
  ~50 s of the command's runtime. Measured on a 200-query sample, the
  250-resample edge is within 0.01 of the 1000-resample edge (pinned by a
  test); the overall block keeps 1000.
