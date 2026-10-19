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

## Owner actions

1. Review this register and the A8-08 targets; the owner ratifies targets
   (I10), the agent only records them.
2. Add the retrieval or prompt change you want measured as a *new* entry in
   the changelog of `thresholds_v1.json` (version bump) before running it.
3. Fill the human sample in `judge_agreement_sample.json` so the judge can be
   used as a metric of record (see `judge-agreement.md`).
