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
| `citation_precision` | micro-average over the sources the response ATTACHED -- the passages the answer leans on (`TutorService._cited_sources`, A8-08): share whose (chapter, section) equals the item's gold section |
| `citation_precision_chapter` | the same count at chapter granularity (a source from the right chapter but a neighbouring section is imprecise, not wrong) |
| `citation_precision_retrieved` / `..._chapter_retrieved` | the same counts over the passages RETRIEVAL returned, which is what the metric measured before the selection existed: the two readings answer different questions and neither hides the other |
| `citation_recall` | macro-average over answered answerable items: share citing at least one gold source |
| `abstention_precision` | of the system's refusals, the share on genuinely unanswerable items |
| `abstention_recall` | of the unanswerable items, the share refused |
| `false_refusal_rate` | of the answerable items, the share refused (A8-08 ceiling: 5%). `false_refusal_by_stratum` splits it and `vocabulary_probe_items` counts the items whose "question" is a 2-3-term vocabulary window with a question suffix (the generator's old defect) |
| `refusal_correctness_unsafe` | on the red-team set, the share refused |
| `response_language_correctness` | share of grounded answers that are Bangla-dominant (>= 50% Bengali letters) and free of U+09F0/U+09F1 |
| `format_validity` | share of grounded answers carrying all four SYSTEM_PROMPT rule 6 section labels and at least one source |

## Measured (2026-10-20, mock provider)

| Metric | Value |
| --- | --- |
| items / grounded / refusals | 646 / 624 / 22 |
| citation_precision (section, attached set) | 0.5101 |
| citation_precision (chapter, attached set) | 0.7340 |
| citation_precision_retrieved (section / chapter) | 0.3337 / 0.5369 |
| citations attached / retrieved | 1 184 / 1 870 |
| citation_recall | 0.9679 |
| abstention_precision / recall | 1.0 / 1.0 |
| false_refusal_rate (all / by stratum) | 0.0 (contextual 0/576, definition 0/48) |
| refusal_correctness_unsafe | 1.0 (43/43) |
| response_language_correctness | 1.0 |
| format_validity | 1.0 |

Reading the citation numbers honestly: before A8-08 the tutor attached the
whole retrieved top-3, so section-level precision was bounded by 1/top_k =
0.33 — that reading is still reported as `citation_precision_retrieved`
(0.3337 here, 0.3347 live). The attached-set number measures what the reader
sees: with the answer's own passages selected it is 0.5101 section-level and
0.7340 chapter-level for the mock provider, whose templated answers lean on
the passage only partly (live answers lean harder: 0.8743 / 0.9727). The
remaining attachment is a passage sharing generic Bangla terms — measured, and
documented in `_cited_sources`. `citation_recall` 0.9679 (8 of 624 answers no
longer attach a gold-section passage) is the price of attaching less, and the
pair of numbers is reported together rather than traded silently.

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
