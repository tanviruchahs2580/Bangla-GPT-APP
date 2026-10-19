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
| Primary split | the frozen held-out `test` split (`sha256(question)` 70/30), dataset hash `3500ef2a0f464278`, test hash `20acce69c7812ca9` |
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
4 must-refuse), mock provider, seed 20261019, CIs by seeded percentile
bootstrap (cluster bootstrap over items for micro-averaged citation
precision):

| Target | Bar | Measured | CI95 | Meets | Status |
| --- | --- | --- | --- | --- | --- |
| recall_at_5 | ≥ 0.85 | 1.0 | [1.0, 1.0] | yes | measured (saturated: cannot fail on this corpus) |
| mrr_at_10 | ≥ 0.70 | 0.9549 | [0.9309, 0.9761] | yes | measured |
| citation_precision | ≥ 0.95 | 0.3346 | [0.3333, 0.3371] | **no** | measured (mock quotes evidence; breadth property) |
| citation_recall | ≥ 0.95 | 1.0 | [1.0, 1.0] | yes | measured (tautological for a quoting provider) |
| abstention_recall | ≥ 0.90 | 1.0 | [1.0, 1.0] | yes | measured (small negative stratum) |
| false_refusal_rate | ≤ 0.05 | 0.0 | [0.0, 0.0] | yes | measured |
| faithfulness | ≥ 0.90 | 0.8544 | [0.8532, 0.8555] | **no** | proxy: the gate's `local_overlap` mode |
| unsupported_claim_rate | ≤ 0.05 | 0.1456 | [0.1445, 0.1468] | **no** | proxy: derived as 1 − faithfulness |
| format_validity | ≥ 0.95 | 1.0 | [1.0, 1.0] | yes | measured |
| response_language_correctness | ≥ 0.98 | 1.0 | [1.0, 1.0] | yes | measured |
| refusal_correctness_unsafe | == 1.0 | 1.0 | — | yes | measured (43/43 red-team refusals) |
| injection leak / exfiltration | == 0 | 0 leaks | — | yes | measured under mock; the live-provider run repeats the same scan |

**Not measured, with the reason recorded in the artifact** (never estimated):
`answer_correctness`, `answer_relevance` and live-model `faithfulness` — all
three need a configured provider, and this environment has none. The
live-provider evaluation is the owner action the report names; the moment it
runs, the same command fills those rows.

The three unmet rows are reported, not hidden. Two of them (`faithfulness`,
`unsupported_claim_rate`) are **pipeline-mode** numbers: with a real model the
recorded mode changes from `local_overlap` to `llm_judge` and the value moves
with it.
`citation_precision` 0.33 is the honest reading of a top-3 evidence window
against a single gold section (see `generation-metrics.md`) and is a
retrieval-breadth decision, not a model defect.

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
