# Judge prompt v1 — faithfulness/groundedness (A8-04)

| | |
| --- | --- |
| Owner | AI-quality owner (see `.github/CODEOWNERS`) |
| Status | active — version 1 |
| Prompt model | any provider the platform supports; the model used must be recorded in the agreement study and must differ from the generator where possible |
| Used by | the judge-human agreement study (`eval/judge_agreement_sample.json`) and, once agreement passes, live generation-metric runs |

The prompt is the fenced block below and nothing else in this file. Its
version is the SHA-256 digest of that block (`bangla_gpt_api.evaluation.generation.judge_prompt_version`),
so editing the prompt changes the version automatically and an old report can
never be mistaken for a run of the new prompt. The changelog below is not part
of the prompt.

Changelog:

- 2026-10-19 — v1 created. Same task shape as the deterministic CI fallback in
  `apps/api/src/bangla_gpt_api/evaluation/metrics.py` (`_JUDGE_INSTRUCTION`),
  promoted to a versioned artifact because a judge used as a metric of record
  needs an identity and an agreement study.

```text
You are a strict faithfulness judge for a Bangla tutoring system. You are given
a student question, excerpts from the approved textbook, and a candidate
answer produced by a tutoring model. Score how much of the answer is supported
by the excerpts: a score of 1 means every claim in the answer is supported by
the excerpts; 0 means the answer is unsupported or contradicts them. Ignore
answer length, style and formatting; judge only factual support. Reply with a
single number between 0 and 1 and no other text.
```
