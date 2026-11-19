# Human-labelled retrieval evaluation set — schema (T-14)

This directory holds the **human** provenance class of the retrieval
evaluation. The repository ships **no data** here: labelling Bangla queries
against the served corpus is a human task (V2 HO-4 — teachers and students).
The schema below is what `bangla_gpt_api.evaluation.human_eval.load_human_eval`
accepts; nothing else counts as human evidence.

## File format

One JSON file (conventionally `human_eval.json`):

```json
{
  "provenance": "human",
  "items": [
    {
      "query": "the student's question, as typed",
      "expected_chunk_ids": ["chunk-id-from-the-corpus-manifest"],
      "class_level": 6,
      "subject": "science",
      "annotator_id": "teacher-01",
      "date": "2026-11-20"
    }
  ]
}
```

Rules the loader enforces:

- top-level `provenance` MUST be the string `human` — anything else is
  rejected (`synthetic_from_corpus` sets live in their own files and are
  never merged with this class);
- every item carries all six required fields (`query`, `expected_chunk_ids`,
  `class_level`, `subject`, `annotator_id`, `date`);
- `expected_chunk_ids` references chunk ids from the built corpus manifest,
  so relevance is verifiable against the served corpus identity.

## How the numbers are used

- CI prints the set status (`HUMAN SET: ABSENT` today) and never merges these
  numbers with synthetic ones.
- The `require_human_eval` gate flag (off by default) fails a run when a
  human set below the configured minimum is required — intended for release
  gating only, not everyday CI.
- The interval width (not the item count) is what says how much a number can
  be trusted; the harness reports a seeded bootstrap 95% CI beside every
  aggregate.
