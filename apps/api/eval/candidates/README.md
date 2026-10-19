# Candidate eval items

Output directory of `apps/api/scripts/eval_loop.py` (A8-09). Files are written
per run, dated, and are the working set of the weekly triage — not committed
state:

| File | Written by | Meaning |
| --- | --- | --- |
| `candidates_<date>.jsonl` | `--db ... --trace-log ...` | one candidate evaluation item per rated tutor message, with the joined trace |
| `triage_<date>.json` | the same run | the sheet a human fills (`verdict`, `answerability`, `reviewer`) |
| `gap_backlog_<date>.json` | the same run | privacy-safe low-coverage aggregates (no question text) |
| `approved_<date>.jsonl` | `--triage <file>` | golden-shaped items from accepted/edited candidates |

The procedure, the join rules and the privacy properties are in
`docs/evaluation/online-loop.md`. Nothing here is a label: an approved item
still needs a teacher's sign-off before it enters the golden set.
