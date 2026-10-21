# Judge-human agreement procedure (A8-04)

Command: `cd apps/api && python -m bangla_gpt_api.evaluation.cli --judge-agreement`.
Files: `apps/api/eval/judge_prompt_v1.md` (the versioned prompt),
`apps/api/eval/judge_agreement_sample.json` (the 50-item sample),
`apps/api/src/bangla_gpt_api/evaluation/generation.py` (the harness).

## Why this file exists

The audit allows an LLM judge as a metric source only with (a) a versioned
judge prompt and (b) measured judge-human agreement on at least 50
human-labelled items, plus bias checks. Without human labels no judge number
may be reported: the harness returns `owner_action_required` rather than a
placeholder score. This environment has no humans, so the deliverable is the
harness plus the procedure below.

## The sample

`judge_agreement_sample.json` holds 50 answerable golden items, sampled by
round-robin over sorted (class_level, subject, stratum) groups so the study can
fail for a class the judge handles badly (regenerate deterministically with
`generation.build_judge_sample`). Each row carries:

| Field | Meaning |
| --- | --- |
| `item_index` | position in `apps/api/eval/golden_v2.json` |
| `question` | the question the judge will see |
| `judge_score` | 0..1 from the judge prompt; null until filled |
| `answer_chars` | answer length in characters, for the verbosity probe |
| `human_label` | 0/1 independent human judgement; null until filled |

## Procedure (owner action)

1. Run the deployed provider over every question in the sample with the exact
   prompt text from `judge_prompt_v1.md`; record `judge_score` and
   `answer_chars`. Record `judge_model` and `generator_model` in the file
   header — self-preference is flagged automatically when they are equal, and
   the judge should differ from the generator where possible.
2. Have a Bangla-speaking reviewer (teacher or native speaker) label each
   answer 0/1 independently of the judge score. A second reviewer on 10 items
   gives a human-human agreement ceiling.
3. Run `--judge-agreement`. The report shows raw agreement, Cohen's kappa, the
   0.4 floor, and `passes_floor`. The harness reports nothing below 50
   labelled items, and marks `kappa_degenerate` when both raters are constant
   (kappa is undefined there — extend the sample with the missing label class
   instead of reading raw agreement as success).
4. Only when `passes_floor` is true may the judge be cited as a metric source,
   with the prompt version, judge model and agreement numbers recorded together
   in the evaluation report.

## Bias checks

| Check | Implementation | Interpretation |
| --- | --- | --- |
| Verbosity | Pearson r between judge score and `answer_chars`; `flagged` at abs(r) >= 0.5 | a flagged run means re-prompt or drop the judge for that metric class |
| Position | reported `not_applicable` — the judge is pointwise (one answer per prompt), so there is no order to swap | if a pairwise judge is ever adopted, this must become a swap test |
| Self-preference | `self_preference_flag` from judge_model == generator_model | a flagged run needs a different judge model before use |

## Until then

The graded columns of the class-appropriateness and synthetic-item review
sheets, and faithfulness in the CI gate, use the deterministic fallbacks that
say what they are (`local_overlap`, blank human columns, `owner_action_required`).
No generation metric in this repository is currently backed by an LLM judge.
