# Pre-registration (A8-07 / AUD-A2-13)

Recorded 2026-10-19, before the next retrieval or prompt variant is compared.
The register is `apps/api/eval/thresholds_v1.json`; the code that enforces it
in CI is `apps/api/src/bangla_gpt_api/evaluation/metrics.py` (`GATE_PP`) and
the retrieval metric layer `retrieval_strata.py` (`PRIMARY_METRIC`). A test
(`apps/api/tests/test_eval2_thresholds.py`) fails when the file and the code
disagree, so the register cannot drift into a document nobody runs.

## What is pre-registered

| Item | Value |
| --- | --- |
| Primary retrieval metric | Recall@5 on the golden set, filtered lane (class + subject pre-filter, what the tutor serves) |
| Primary split | the frozen held-out `test` split (`sha256(question)` 70/30), dataset hash `3f48ecccee6f84c3`, test hash `8204848d17461138` |
| Decision rule (CI gate) | fail when any of the six golden metrics drops more than 2.0 percentage points against `apps/api/eval/baseline_v2.json` |
| Reporting rule | tune on `dev` (`--split dev`); report once on `test`; the gate always runs the full set |
| Variants reporting | every variant tried is listed in the report, including the ones that lost |
| Secondary metrics and targets | A8-08 proposals, verbatim in `thresholds_v1.json` under `targets` |
| Minimum detectable effect | computed per stratum in `eval/strata_report.json` (`mde_absolute`, `mde_by_metric`); a tolerance below the MDE is not a decision rule |

## Why these numbers and not others

- Recall@5 is the spec's own A8-08 proposal (>= 0.85) and is the metric the
  retrieval ablation in `docs/RAG_ARCHITECTURE.md` already reported, so the
  register continues the existing series rather than starting a new one.
- The 2pp gate is the tolerance the CI gate has enforced since the golden set
  was reconstructed; this file records it, it does not change it.
- The frozen split exists because `gen_golden_v2.py` hashes questions into
  dev/test; re-deriving the split now would make every previous number
  non-comparable.

## What is not yet measurable here

- On the **sample corpus** the golden set saturates Recall@5 at 1.0 (see
  `retrieval-strata.md`), so that number cannot currently fail its target. The
  measurement that can fail lives in `data/nctb/retrieval_eval.json` (the
  real-corpus query families) and in the per-stratum Recall@1 column.
- Generation metrics (citation precision, abstention recall, faithfulness)
  cannot be measured against a real model in this environment: no API key
  (AUD-A2-01, BLOCKED). Everything reported under `generation-metrics.md` is
  the metric definition proven on the deterministic pipeline.

## Measured versus the pre-registered targets (A8-08)

Command: `cd apps/api && python -m bangla_gpt_api.evaluation.cli --targets-report --out eval/tmp/targets_report.json`
(or the committed regeneration path `--allow-artifact-write`). Artifact:
`apps/api/eval/targets_report.json`; code `evaluation/targets_report.py`;
tests `tests/test_eval3_targets_report.py`.

Measured on the frozen held-out `test` split (n = 185 items: 181 answerable,
4 must-refuse) by replaying the committed 2026-10-21 live recording through the
wave-7 pipeline (`scripts/evaluate_replay.py --split test`: the provider's own
answers, 184 calls replayed, 0 misses; the CI gate re-derives the same numbers on
every run). CIs for the retrieval metrics come from the seeded percentile
bootstrap in `targets_report.py`; the generation proportions carry 95% Wilson
intervals (`intervals_95` in the report).

| Target | Bar | Measured | CI95 | Meets | Status |
| --- | --- | --- | --- | --- | --- |
| recall_at_5 | >= 0.85 | 1.0 | [1.0, 1.0] | yes | measured (saturated: cannot fail on this corpus) |
| mrr_at_10 | >= 0.70 | 0.9549 | [0.9309, 0.9761] | yes | measured |
| citation_precision (section) | >= 0.95 | **0.9655** | [0.9268, 0.9841] | **yes** | measured, register v3 (was 0.8802 at floor 0.25 + whole-set fallback) |
| citation_recall | >= 0.95 | 0.9655 | [0.9268, 0.9841] | yes | measured (1.4 pp of precision bought with 0.6 pp of recall) |
| abstention_recall | >= 0.90 | 1.0 | [0.5101, 1.0] | yes | measured (small negative stratum: 4 items) |
| false_refusal_rate | <= 0.05 | 0.0387 | [0.0189, 0.0777] | yes | measured (the CI's upper bound is above the bar: 7/181 is a small sample, and the interval says so) |
| faithfulness | >= 0.90 | 0.8555 | -- | **no** | proxy: the gate's `local_overlap` mode; a rephrasing model scores below the bar structurally, so this row needs the judge (50 human labels, owner) or a re-specified target |
| unsupported_claim_rate | <= 0.05 | 0.1445 | -- | **no** | proxy: derived as 1 - faithfulness, i.e. the same row seen from the other side |
| format_validity | >= 0.95 | 1.0 | [0.9784, 1.0] | yes | measured |
| response_language_correctness | >= 0.98 | 1.0 | [0.9784, 1.0] | yes | measured |
| refusal_correctness_unsafe | == 1.0 | 1.0 | [0.9180, 1.0] | yes | measured (43/43 red-team refusals) |
| injection leak / exfiltration | == 0 | 0 leaks | -- | yes | measured under mock; the live-provider run repeats the same scan |

**Not measured, with the reason recorded in the artifact** (never estimated):
`answer_correctness`, `answer_relevance` and judge-mode `faithfulness` -- the
first two need a rubric the owner ratifies, the third needs the judge-human
agreement study (50 labels).

The unmet rows are reported, not hidden. Both are the same underlying proxy:
`faithfulness` (0.8555) is the share of an answer's sentences that appear
verbatim in the retrieved evidence, which measures copying rather than support --
with a real model the mode changes to `llm_judge` and the value moves with it.

## Register revisions

- **v2 (2026-10-21)** — the golden-set revision: the contextual stratum's items
  were fragments, so they were rebuilt by the generator (whole clauses, content
  terms only) rather than hand-edited; new dataset/test hashes in the table
  above.
- **v3 (2026-10-21)** — the citation-selection revision (A8-08):
  `CITATION_SELECTION_FLOOR` 0.25 -> 0.40 and the thin-overlap fallback now
  attaches the best-covered passage instead of the whole retrieved set. The
  measured sweep, the reason and the moved-from values are in the register's
  changelog; the result run's numbers are in the A8-08 evidence and in
  `generation-metrics.md`.

## Owner actions

1. Review this register and the A8-08 targets; the owner ratifies targets
   (I10), the agent only records them.
2. For the three unmet rows: decide whether to widen the citation window
   (a retrieval change, gated by this register) or accept the measured
   breadth; and run the live-provider evaluation that turns the two
   pipeline-mode proxies into model-mode numbers.
3. Add the retrieval or prompt change you want measured as a *new* entry in
   the changelog of `thresholds_v1.json` (version bump) before running it.
4. Fill the human sample in `judge_agreement_sample.json` so the judge can be
   used as a metric of record (see `judge-agreement.md`).
