# Teacher review queue for synthetic golden items (A2-11)

Command: `cd apps/api && python -m bangla_gpt_api.evaluation.cli --export-synthetic-sheet`.
Artifacts: `apps/api/eval/review_sheets/synthetic_review_sheet.csv` (the work
item), `apps/api/eval/synthetic_review_ledger.json` (the only record of human
review), `apps/api/src/bangla_gpt_api/evaluation/review_sheet.py` (the
exporter, validator and ledger writer).

## The rule this queue enforces

Every golden item is machine-built (`synthetic: true`) and is **never**
presented as human-verified (A8-02). The only route out of that state is a
recorded human verdict in the ledger; there is no code path that flips the
flag, and the sheet's human columns ship blank so a machine cannot fill them by
accident.

## Working the queue

1. Export the pending queue (already-reviewed items are skipped):

   ```text
   python -m bangla_gpt_api.evaluation.cli --export-synthetic-sheet
   ```

   The sheet is UTF-8-with-BOM CSV, which is what Excel needs to render Bangla.
   Columns: identity and provenance (`item_id`, class, subject, stratum, split,
   chapter, section), the `question` and its `expected` behaviour, then the
   blank human columns `verdict`, `corrected_question`, `corrected_expected`,
   `review_comment`, `reviewer`, `reviewed_at`.

2. Queue order is fixed and documented
   (`review_sheet.queue_priority`): must-refuse items first (they carry the
   abstention claims), then the `definition` stratum (section glosses the
   generator leans on), then `contextual` items; ties keep the golden file's
   order, so two reviewers work the same queue.

3. Fill one of three verdicts per row:

   | Verdict | Meaning | Required fields |
   | --- | --- | --- |
   | `approve` | the question is answerable from the cited section and appropriate for the class | `reviewer` |
   | `reject` | the item is wrong, ambiguous or off-curriculum | `reviewer` (a `review_comment` is strongly expected) |
   | `edit` | the item is usable after a correction | `reviewer` plus `corrected_question` or `corrected_expected` |

   A blank verdict means "still pending" and is not an error. A verdict without
   a reviewer name is rejected — an unattributable approval is not a review.

4. Apply the sheet:

   ```text
   python -m bangla_gpt_api.evaluation.cli --apply-review-sheet <filled.csv>
   ```

   Validation failures exit 1 with the line number; valid rows merge into the
   ledger with reviewer and date. `--review-status` prints the counts
   (`approved` / `rejected` / `edited` / pending) at any time.

## What approving does and does not do

- Approving records human judgement; it does not edit the golden set. Items
  whose question or expectation changes with `edit` are applied to the dataset
  by the owner through the normal dataset-change path: regenerate
  `apps/api/eval/golden_v2.json`, regenerate the baseline **in the same
  change**, and report the old and new metric values (the repo's rule against
  re-baselining to go green).
- Rejections stay in the ledger so a rejected question cannot silently return.
- The ledger is per item id (`sha1(class|subject|question)[:12]`), which is
  stable as long as the question text is.

## Current state

`--review-status` reports 0 of 646 reviewed: the sheet exists, the queue order
is defined, and no human has worked it yet. The ledger file appears on the
first `--apply-review-sheet` run.

## Owner actions

1. Assign the sheet to a teacher or Bangla native speaker (class-appropriate
   expertise per item; the sheet is ordered so a whole class can be batched).
2. Return the filled sheet and run `--apply-review-sheet`.
3. After sign-off, decide whether the reviewed set replaces the synthetic one
   or is published alongside it (this changes a baseline and is an owner
   decision, not an agent one).
