# Generation metrics and the judge gate (A8-04)

Command: `cd apps/api && python -m bangla_gpt_api.evaluation.cli --generation-report`.
Artifact: `apps/api/eval/generation_report.json` (golden set = 646 items plus
the 43-case red-team set, mock provider, hermetic).

## Metric definitions

Each definition is implemented in
`apps/api/src/bangla_gpt_api/evaluation/generation.py` and pinned by a test in
`apps/api/tests/test_eval2_generation.py` on hand-built responses, so no
number below rests on a definition that only exists in prose.

| Metric | Definition |
| --- | --- |
| `citation_precision` | micro-average over attached sources: share whose (chapter, section) equals the item's gold section |
| `citation_precision_chapter` | the same count at chapter granularity (a source from the right chapter but a neighbouring section is imprecise, not wrong) |
| `citation_recall` | macro-average over answered answerable items: share citing at least one gold source |
| `abstention_precision` | of the system's refusals, the share on genuinely unanswerable items |
| `abstention_recall` | of the unanswerable items, the share refused |
| `false_refusal_rate` | of the answerable items, the share refused (A8-08 ceiling: 5%) |
| `refusal_correctness_unsafe` | on the red-team set, the share refused |
| `response_language_correctness` | share of grounded answers that are Bangla-dominant (>= 50% Bengali letters) and free of U+09F0/U+09F1 |
| `format_validity` | share of grounded answers carrying all four SYSTEM_PROMPT rule 6 section labels and at least one source |

## Measured (2026-10-19, mock provider)

| Metric | Value |
| --- | --- |
| items / grounded / refusals | 646 / 624 / 22 |
| citation_precision (section) | 0.3337 |
| citation_precision (chapter) | 0.5374 |
| citation_recall | 1.0 |
| abstention_precision / recall | 1.0 / 1.0 |
| false_refusal_rate | 0.0 |
| refusal_correctness_unsafe | 1.0 (43/43) |
| response_language_correctness | 1.0 |
| format_validity | 1.0 |

Reading the citation numbers honestly: the tutor attaches the top-3 retrieved
passages as sources, so section-level precision of 0.33 means roughly one of
three listed passages is the exact gold section and the other two are
elsewhere — for the mock provider, which quotes its evidence verbatim, that is
a retrieval-breadth property, not an answer defect. Chapter-level precision
(0.54) is the same fact at coarser granularity. `citation_recall` 1.0 is a
tautology for this provider and is reported only because the definition must
exist and be exercised before a live run.

## The judge is not a metric of record yet

- The judge prompt is versioned by the digest of its fenced block in
  `apps/api/eval/judge_prompt_v1.md` (header and changelog are not part of the
  version). Reports record it under `judge_prompt_version`.
- `--judge-agreement` prints the state of
  `apps/api/eval/judge_agreement_sample.json`: 50 items with null
  `judge_score`/`human_label`, so the harness answers
  `owner_action_required` and reports **no** agreement number. That is the
  correct state: the audit requires judge-human agreement on at least 50
  human-labelled items before a judge may be used, and no humans exist in this
  environment. See `judge-agreement.md` for the procedure.
- Bias checks are implemented and reported with the harness: verbosity bias as
  the Pearson correlation between judge score and answer length (flagged at
  |r| >= 0.5), position bias explicitly ``not_applicable`` because the judge is
  pointwise (one answer per prompt), and self-preference flagged when the
  judge model equals the generator model.

## Limits

- No live provider, so answer correctness, answer relevance and
  LLM-judge faithfulness are **not measured** here (AUD-A2-01, BLOCKED). The
  deterministic CI gate keeps its honest `local_overlap` fallback, labelled as
  such in its output.
- A live run is an owner action: set `GEMINI_API_KEY`, add `LLM_PROVIDER` to
  the environment, and re-run the same command; the report records the
  provider string so a mock run can never be mistaken for a live one.
