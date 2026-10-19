# Evaluation plane

Everything here is about measuring the tutor: retrieval ranks, answer quality,
cost and load. Each document names the artifact it reads, the command that
regenerates it and who owns the human step.

| Document | Finding | Artifact / command |
| --- | --- | --- |
| `pre-registration.md` | A8-07 / AUD-A2-13 | `apps/api/eval/thresholds_v1.json`, `python -m bangla_gpt_api.evaluation.cli --check-thresholds` |
| `pre-registration.md` §measured | A8-08 | `apps/api/eval/targets_report.json`, `python -m bangla_gpt_api.evaluation.cli --targets-report --out eval/tmp/targets_report.json` |
| `retrieval-strata.md` | A8-03 / AUD-A2-12 | `apps/api/eval/strata_report.json`, `python scripts/strata_report.py` |
| `retrieval-variants.md` | A4-01 / A4-02 / A4-07 / A4-08 / A4-09 | `apps/api/eval/variant_matrix.json`, `data/nctb/retrieval_eval.json`, `python -m bangla_gpt_api.evaluation.cli --variant-matrix --out eval/tmp/variant_matrix.json` |
| `query-understanding.md` | A4-03 / A4-04 / A4-06 | `data/nctb/retrieval_eval.json` (`lexicon_audit`, `banglish_subset`, `gate_threshold_calibration`), `apps/api/scripts/evaluate_nctb_retrieval.py` (run from `apps/api`) |
| `index-and-ann.md` | A3-05 / A3-06 | `apps/api/eval/index_budget.json`, `apps/api/eval/ann_sweep.json`, `python -m bangla_gpt_api.evaluation.cli --index-budget` / `--ann-sweep` |
| `generation-metrics.md` | A8-04 | `apps/api/eval/generation_report.json`, `python -m bangla_gpt_api.evaluation.cli --generation-report` |
| `judge-agreement.md` | A8-04 | `apps/api/eval/judge_agreement_sample.json`, `python -m bangla_gpt_api.evaluation.cli --judge-agreement` |
| `synthetic-item-review.md` | A2-11 | `apps/api/eval/review_sheets/synthetic_review_sheet.csv`, `python -m bangla_gpt_api.evaluation.cli --export-synthetic-sheet` |
| `class-appropriateness-rubric.md` | A11-01 | `apps/api/eval/review_sheets/class_appropriateness_sheet.csv`, `python -m bangla_gpt_api.evaluation.cli --export-appropriateness-sheet` |
| `online-loop.md` | A8-09 | `apps/api/scripts/eval_loop.py` |
| `cost-model.md` | A2-20 / A9-02 | `apps/api/eval/cost_report.json`, `python scripts/cost_report.py` |
| `load-harness.md` | A9-05 / A9-01 | `apps/api/eval/load_report.json`, `apps/api/eval/stage_latency.json`, `python scripts/loadgen.py`, `python -m bangla_gpt_api.evaluation.cli --stage-latency` |
| `change-management.md` | AUD-A2-13 | `bangla_gpt_api.evaluation.thresholds`, `apps/api/eval/reindex_drill.json` |

Commands run from `apps/api` unless the row says otherwise. The CI regression
gate itself is unchanged: `python -m bangla_gpt_api.evaluation.cli` compares
the golden set against `apps/api/eval/baseline_v2.json` and fails on a drop
greater than 2 percentage points.

## One command, every reported number (A8-10)

```bash
cd apps/api
make rag-eval          # or: python -m bangla_gpt_api.evaluation.cli --rag-eval
make rag-eval-fast     # ... skipping the corpus-scale producers
```

`--rag-eval` runs every producer on this page into **one untracked run
directory** (`apps/api/eval/tmp/rag_eval/<run-id>/`, ignored by the
repository's `tmp/` rule — asserted by a test with `git check-ignore`), writes
one JSON per producer plus `summary.json` and `summary.md`, and records the
seeds, the prompt version, the golden dataset hashes and the package versions
in the summary. It finishes by re-reading `git status` and printing whether
the run changed any tracked file: the property is checked, not promised.

Artifacts per run: `gate.json`, `redteam.json`, `generation_report.json`,
`generation_rows.json`, `strata_report.json`, `variant_matrix.json`,
`targets_report.json`, `thresholds.json`, `stage_latency.json`,
`drift_report.json` / `drift_report.md`, and — when `data/nctb` is built —
`index_budget.json`, `ann_sweep.json`, `nctb_retrieval_eval.json`. The
corpus-scale producers are skipped with `--no-corpus` (or when the corpus is
absent) and the skip is recorded in the summary.

The committed artifacts under `apps/api/eval/` are the *deliberate*
regeneration path: running an individual producer flag with an explicit path
updates them, and the CLI **refuses** to overwrite a git-tracked file unless
`--allow-artifact-write` is passed, so a casual run cannot dirty the tree.

The Makefile target text the repository root needs (the root `Makefile` is
owned elsewhere; `apps/api/Makefile` already ships the same targets):

```text
rag-eval: ## A8-10: every evaluation number into eval/tmp/rag_eval/<run-id>/
<TAB>$(PY) -m bangla_gpt_api.evaluation.cli --rag-eval

rag-eval-fast: ## ... skipping the corpus-scale producers
<TAB>$(PY) -m bangla_gpt_api.evaluation.cli --rag-eval --no-corpus
```

Replace `<TAB>` with a real tab: make requires recipe lines to start with one,
and a markdown-lint fixer rewrites literal tabs, so the working tab lives in
`apps/api/Makefile` rather than in this page.

Two limits apply to every number in these documents and are repeated where
they matter: the provider in this environment is `mock` (no `GEMINI_API_KEY`),
so generation-side figures are pipeline measurements, not model-quality
measurements; and human judgement (teacher review, native-language review,
judge agreement) is an owner action, never a machine substitute.
