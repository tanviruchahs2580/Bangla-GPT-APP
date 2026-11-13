# R@1 regression investigation (V4 Phase 1) — `0.95 → 0.87`

Status: **RESOLVED as a comparability artifact, not a code regression.** No label, denominator,
query or threshold was changed. Reproduction commands below.

## 1. The two numbers measure different corpus revisions

| Artifact | Commit | Evaluated at | `index_chunks` | `corpus_digest` | Family-A R@1 |
|---|---|---|---|---|---|
| Committed 0.95 | `7b1b90e` (2026-11-03) | 2026-11-03T09:11:28Z | 1605 | `d574832089eacf33ae80…` | **0.95** |
| Current | `969e499` (2026-11-13) | 2026-11-12T22:08:16Z | 1598 | `1396faf223aeccf5e6a4…` | **0.87** |

`[cmd] git show 7b1b90e:data/nctb/retrieval_eval.json` vs `data/nctb/retrieval_eval.json` — the
digests differ, so the inputs to the metric are not the same. Per V4 §4.2/§4.4 these results must not
be compared as a regression pair without reconciliation.

## 2. Code contributes ZERO to the difference (decomposition, same corpus both sides)

| Configuration | Corpus | Family-A R@1 | MRR |
|---|---|---|---|
| Nov-3 code (`7b1b90e`) — this branch's parent lineage | current (digest `1396faf2…`) | **0.87** | **0.9212** |
| Pre-v2 main (`d6f3342`) — isolated in an earlier worktree | current | **0.87** | **0.9212** |
| Current main lineage (this branch) | current | **0.87** | **0.9212** |

Reproduction: `git worktree add <tmp> 7b1b90e && cp -r data/nctb/normalized <tmp>/data/nctb/ &&`
`cd <tmp>/apps/api && python scripts/evaluate_nctb_retrieval.py <tmp>/data/nctb` — all three produce
byte-identical family-A blocks. **No code revision between 2026-11-03 and today moved this metric on a
fixed corpus.**

## 3. First causative change: the corpus rebuild of 2026-11-11

`[cmd] git log --format='%h %cs %s' -- data/nctb/manifests/corpus_manifest.json`:

```
969e499 2026-11-13 chore(rag): regenerate the real-corpus retrieval report after the v2 stages
9890b3e 2026-11-11 chore(rag): rebuild the corpus so the manifest fingerprint matches the tree
05d95a5 2026-11-11 fix(rag): rebuild the corpus text pipeline and make its gate blocking
7b1b90e 2026-11-03 chore(rag): rebase polish — …v3 corpus artifacts regenerated
```

`05d95a5` rebuilt the corpus text pipeline (manual `built_at 2026-11-11T00:30:34Z`). The rebuild
changed chunk boundaries/text (digest change), which changes both the sampled family-A queries
(generated from the chunks with a fixed seed) and their competitor sets. The old corpus bytes are
untracked and were legitimately overwritten by the rebuild workflow, so exact re-measurement of the
0.95 number is not reproducible; the committed artifact preserves it (V4 §4.2.10 limitation recorded
here rather than silently regenerated).

## 4. Per-query error taxonomy on the current corpus (n=100, deterministic)

`[cmd] cd apps/api && python scripts/diagnose_family_a.py ../../data/nctb` →
`{"rank1": 87, "twin-shadow": 6, "other-winner": 6, "absent": 1}`

| Category | Count | Definition | Implication |
|---|---|---|---|
| rank-1 hits | 87 | target evidence unit ranked first | matches the published 0.87 exactly |
| twin-shadow | 6 | the winning unit's text **contains** the query words, but is a different evidence unit (near-duplicate passage, boundaries/heading differ) | corpus-content class: near-duplicate units across overlapping curriculum sources; the evaluator's unit identity is finer than the text identity |
| other-winner | 6 | an unrelated unit legitimately outranked (ranks 2–4) | ordinary ranking misses |
| absent | 1 | target unit not in top-5 | worst case, single item |

Note: identical-text class copies are already neutralised by the evaluator (`evidence_unit()` strips
the `-c<level>` suffix) and by ingest dedupe `(content_hash, class)`, so the taxonomy's twin-shadow
class is strictly *near*-duplicates, not exact copies.

## 5. Disposition (V4 §4.4)

- **Not a regression**: no code-caused change exists (given the identical triple-decomposition in §2),
  so there is nothing to revert or fix in the retrieval code path.
- **Actionable follow-up (owner decision)**, evidence in §4: 6/100 family-A cases are near-duplicate
  unit shadows — candidates are (a) evaluator unit-granularity adjustment (documented metric
  definition change, deliberately NOT made here), or (b) near-duplicate collapse in a future corpus
  rebuild (ingestion change → manifest + gates). Both change measured semantics and therefore belong
  in a separately reviewed act, not in this readiness pass.
- **0.95 remains non-binding** as a release gate: proved non-comparable (§1). Current measurable bar:
  R@1 0.87 / R@5 0.99 / MRR 0.9212 (family A), R@1 1.0 (family B), family-C refusal 1.0 — all
  reproducible with the commands above.
- Family-B competitors: `_rank_of` for family B already matches by unit, so the class-expansion wave
  cannot inflate its denominator; its 1.0 stands on the current corpus (re-verified in §2 runs).
