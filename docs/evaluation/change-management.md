# Change management for model, prompt, index and embedding changes (AUD-A2-13)

The evaluation-side hook lives in
`apps/api/src/bangla_gpt_api/evaluation/thresholds.py`; the register it protects
is `apps/api/eval/thresholds_v1.json`; the gates that must run are the same
ones CI already runs.

## The rule

A change to the model, the prompt, the index or the embedding model is a change
to what students receive. It may not ship on a code review alone:

1. **Pre-register before measuring.** Add the change and the metric you expect
   it to move to the changelog in `thresholds_v1.json` and bump `version`
   (exactly one changelog entry per version). `load_thresholds` refuses a file
   whose version and changelog disagree.
2. **Never lower a target silently.** `validate_revision` rejects a revision
   that moves a numeric threshold with an empty changelog entry, and rejects a
   *lowered* target unless the entry carries a written reason in `moved_from`.
   Raising the CI tolerance is itself a moved threshold and needs the same
   entry.
3. **Produce the evidence for the change kind** (below), regenerated *after*
   the change — `stale_evidence` compares the artifact's mtime against the
   changed sources, because evidence recorded before a change is not evidence
   about it.
4. **Run the gates**: `python -m bangla_gpt_api.evaluation.cli` (regression),
   `--redteam` (safety), `--check-thresholds` (this file), and the retrieval
   or generation report for the kind of change.

## Required evidence per change kind

| Change | Required artifacts | Why |
| --- | --- | --- |
| `model` | `apps/api/eval/generation_report.json` | answers change; citation/abstention/language/format metrics and the red-team refusal slice travel with it |
| `prompt` | `apps/api/eval/generation_report.json` | a prompt edit can weaken grounding and citations; the same report carries the safety slice |
| `index` | `apps/api/eval/strata_report.json`, `data/nctb/retrieval_eval.json` | ranks move; both the stratified golden report and the real-corpus families must be regenerated |
| `embedding` | `apps/api/eval/strata_report.json`, `data/nctb/retrieval_eval.json` | an embedding change is an index change: it needs a full re-index and a side-by-side comparison before rollout |

## Version visibility

Every evaluation artifact records the version identities it ran against:
`index_fingerprint` (corpus), `prompt_version` (tutor system prompt digest),
`judge_prompt_version` (judge prompt digest) and the golden dataset hashes.
A report without them cannot be tied to what ran, so their absence is a defect
in the report, not a detail.

## Rollout and rollback

- The app-level blue/green rolling deploy and rollback procedure is
  `docs/operations/PRODUCTION_DEPLOYMENT.md`; this document adds the
  *evaluation* preconditions, not a second deployment mechanism.
- Canary/shadow for model and prompt changes, and index snapshots with atomic
  publish and rollback, are index-lifecycle features already tested in
  `apps/api/tests/test_a1_index_lifecycle.py`; an operator must still decide
  the canary percentages (owner action).

## What is not covered here

Drift monitoring (query-topic distribution versus corpus coverage, corpus
staleness against curriculum updates, A10-04) and canary automation (A10-03's
full procedure) remain open in the AUD-A2-13 register entry; this document
covers the evaluation-side hooks that exist and are enforced by tests.
