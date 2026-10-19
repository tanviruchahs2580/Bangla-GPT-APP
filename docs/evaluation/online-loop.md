# Online loop: feedback to trace to eval item (A8-09)

Command: `cd apps/api && python scripts/eval_loop.py --db <database> --trace-log <log>`.
Artifacts: `apps/api/eval/candidates/` (candidate items, triage sheet, gap
backlog, approved items) and `apps/api/src/bangla_gpt_api/evaluation/` for the
metric side.

## The weekly ritual

1. **Collect traces.** Set `TRACING_ENABLED=true` so the API writes one trace
   record per pipeline stage to stdout; the deployment already ships stdout to
   the log sink. Capture that stream to a file (for example
   `... | tee /var/log/bangla/trace.log`). Trace records carry the request id,
   retrieval coverage, the gate verdict, the retrieved chunk ids, the index and
   prompt versions — and never the student's question text.
2. **Run the loop** for the week:

   ```text
   python scripts/eval_loop.py --db ./dev.db --trace-log /var/log/bangla/trace.log \
       --since-days 7 --out eval/candidates
   ```

   Output: `candidates_<date>.jsonl` (one candidate per rated tutor message —
   thumbs-down or comment-only), `triage_<date>.json` (the sheet to fill) and
   `gap_backlog_<date>.json` (privacy-safe curriculum-gap aggregates).
3. **Triage.** An engineer or teacher fills `verdict`
   (`accept`/`reject`/`edit`), `answerability` (`in_corpus`/`out_of_corpus` —
   this decides the expected behaviour) and `reviewer` in the triage file. Rows
   left blank stay pending.
4. **Apply:**

   ```text
   python scripts/eval_loop.py --triage eval/candidates/triage_<date>.json
   ```

   Accepted and edited candidates become golden-shaped items in
   `approved_<date>.jsonl` with `provenance.kind = student_feedback`,
   `synthetic: false`, `needs_teacher_review: true` and a split assigned by the
   same `sha256(question)` rule the golden generator uses. A teacher still has
   to sign the item off before it enters the set (see
   `synthetic-item-review.md`); merging it is a dataset change and regenerates
   the baseline in the same commit.

## The trace join

A feedback row records only a message id. The join to the trace is explicit
and is recorded per candidate as `trace_join`:

| Method | Rule | Strength |
| --- | --- | --- |
| `citations` | the citation triples (chapter, section, page) derived from the trace's `retrieved_ids` equal the rated answer's own `sources_json` list | exact; requires the corpus to map ids to metadata (`--corpus-dir` for the real corpus, sample corpus by default) |
| `count` | exactly one unused retrieval trace has the same number of evidence chunks | weaker, labelled as such |
| `unmatched` | nothing matched; `trace: null` | never invented — the candidate says so |

## The curriculum-gap backlog

Low-coverage traces (retrieval coverage below 0.5, `LOW_COVERAGE_THRESHOLD`)
are aggregated by class and chapter with counts and mean coverage. The artifact
contains **no question text** — only counts — so ops can read the backlog
without seeing what children asked. Chapter attribution needs the retrieved
ids resolved through the corpus; without it the chapter is null and the count
is kept.

## What is verified

`apps/api/tests/test_eval2_loop.py` runs the whole loop against a real
(throwaway) database: a tutor turn, thumbs-down feedback, captured trace lines,
`trace_join: citations` with the trace id asserted, and the triage step
producing a golden-shaped item. That test is the audit's "traced example from
feedback to a new eval item".

## Limits

- The trace log must be captured out-of-band; the API does not persist traces
  to the database (by design — no student wording in storage). An operator who
  loses the log loses the join for that window; candidates then report
  `unmatched` rather than guessing.
- Feedback without a preceding user turn (a deleted conversation) is skipped
  with a note, exactly as the CLI prints it.
