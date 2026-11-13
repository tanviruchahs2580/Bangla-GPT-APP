# Neighbor-expansion experiment — measured (V4 Phase 3)

Date: 2026-11-13 · Branch: `feat/bangla-gpt-rag-v4-readiness` · Fix: `aa3d7be`

## What was tested

`RAG_NEIGHBOR_EXPANSION` (retrieval engine v2, expansion stage —
`retrieval/expansion.py`): for each selected top hit, the adjacent chunks in
the same `(source, class_level, chapter, section)` bucket slot in after it,
before the grounding gate reads the evidence. Flag OFF by default
(`config.py::rag_neighbor_expansion = False`).

## First finding: the experiment was previously unmeasurable

The eval CLI's `_build_tutor` (`evaluation/cli.py`) built a bare
`HybridIndex` and never consumed the flag — `RAG_NEIGHBOR_EXPANSION=true`
graded the same stack as `false`. Two pilot runs (n=60, seed 20261029)
returned byte-identical metrics, which is what exposed it. `aa3d7be` wires
the expander into the CLI exactly as `initialize/dependencies.py` does.
Verified after the fix: `_build_tutor(Settings)` returns a tutor with
`neighbor_expander is not None` under `RAG_NEIGHBOR_EXPANSION=true`.

## Measured result (hermetic golden gate, n=427, seed 20261029)

| Leg | grounded_rate | coverage_true | faithfulness_avg | hit@3 | Gate |
| --- | --- | --- | --- | --- | --- |
| OFF | 0.8080 | 0.7980 | 0.8544 | 404/406 = 0.9951 | PASS |
| ON  | 0.8080 (bootstrap delta vs baseline +0.0117, CI [+0.0023, +0.0234]) | — | 0.8544 | 0.9951 | PASS |

Both legs: ALL GATES PASS. Paired bootstrap on the ON leg: delta=+0.0117,
95% CI [+0.0023, +0.0234] — "measurable difference" **vs the committed
baseline** (0.7963), not between the two legs; the two legs themselves are
identical.

## Why the legs are identical — structural, not plumbing

The golden suite runs on the 78-chunk bundled sample. Measured:
**0 of the 78 `(source, class_level, chapter, section)` buckets hold more
than one chunk** — every chunk is its own section — so the expander emits no
neighbors for any input. Directly verified: of 423 golden items with
retrievable hits, **0 change** under the expander. The env plumbing itself
was verified working (`Settings` maps `RAG_NEIGHBOR_EXPANSION` → field;
expander present in the eval stack).

On the **real** corpus (847 chunks, `data/nctb/normalized`): 151 buckets
with >1 chunk (max 49), 69 singletons — the flag is structurally meaningful
there. It could not be evaluated against the golden gate because the golden
set is bound to the sample corpus (the gate's identity pins
`corpus_source=bundled_sample`).

## Conclusion

- ON the sample corpus the flag is a provable no-op; all gates pass on both
  legs. **Keeping `RAG_NEIGHBOR_EXPANSION=false` (the current default) is the
  measured recommendation** for the sample-bound golden gate.
- On the real corpus the stage is live code with real neighbor buckets; a
  real-corpus A/B needs an eval suite bound to the real corpus, which does
  not exist today (the committed golden set's items are keyed to the sample
  constructs). That is an owner decision, not a gap this pass can close
  without fabricating corpus-bound labels.
- The reranker and embedder comparisons named in the Phase 3 plan are
  AMBER-blocked: a cross-encoder requires an external endpoint + model
  (owner approval per the V4 authority matrix), and an embedding change is a
  manifest-breaking event. Documented, not attempted.
