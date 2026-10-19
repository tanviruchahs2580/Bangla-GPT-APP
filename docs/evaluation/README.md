# Evaluation plane

Everything here is about measuring the tutor: retrieval ranks, answer quality,
cost and load. Each document names the artifact it reads, the command that
regenerates it and who owns the human step.

| Document | Finding | Artifact / command |
| --- | --- | --- |
| `pre-registration.md` | A8-07 / AUD-A2-13 | `apps/api/eval/thresholds_v1.json`, `python -m bangla_gpt_api.evaluation.cli --check-thresholds` |
| `retrieval-strata.md` | A8-03 / AUD-A2-12 | `apps/api/eval/strata_report.json`, `python scripts/strata_report.py` |
| `generation-metrics.md` | A8-04 | `apps/api/eval/generation_report.json`, `python -m bangla_gpt_api.evaluation.cli --generation-report` |
| `judge-agreement.md` | A8-04 | `apps/api/eval/judge_agreement_sample.json`, `python -m bangla_gpt_api.evaluation.cli --judge-agreement` |
| `synthetic-item-review.md` | A2-11 | `apps/api/eval/review_sheets/synthetic_review_sheet.csv`, `python -m bangla_gpt_api.evaluation.cli --export-synthetic-sheet` |
| `class-appropriateness-rubric.md` | A11-01 | `apps/api/eval/review_sheets/class_appropriateness_sheet.csv`, `python -m bangla_gpt_api.evaluation.cli --export-appropriateness-sheet` |
| `online-loop.md` | A8-09 | `apps/api/scripts/eval_loop.py` |
| `cost-model.md` | A2-20 / A9-02 | `apps/api/eval/cost_report.json`, `python scripts/cost_report.py` |
| `load-harness.md` | A9-05 | `apps/api/eval/load_report.json`, `python scripts/loadgen.py` |
| `change-management.md` | AUD-A2-13 | `bangla_gpt_api.evaluation.thresholds` |

Commands run from `apps/api` unless the row says otherwise. The CI regression
gate itself is unchanged: `python -m bangla_gpt_api.evaluation.cli` compares
the golden set against `apps/api/eval/baseline_v2.json` and fails on a drop
greater than 2 percentage points.

Two limits apply to every number in these documents and are repeated where
they matter: the provider in this environment is `mock` (no `GEMINI_API_KEY`),
so generation-side figures are pipeline measurements, not model-quality
measurements; and human judgement (teacher review, native-language review,
judge agreement) is an owner action, never a machine substitute.
