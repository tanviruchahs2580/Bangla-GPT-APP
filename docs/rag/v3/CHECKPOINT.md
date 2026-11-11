# RAG V3 — Session Checkpoint

Written 2026-11-12 per V3 §23. On resume, **verify HEAD and the working tree**; do not assume
this checkpoint's claims are still true.

## State

| Item | Value |
|---|---|
| Branch | `feat/rag-v3-phase-0-baseline` (created from `main`; `main` untouched at `03dfe21`) |
| Commit SHA | `03dfe21b6f90bc27ca476bfa459318a14bf3d266` — **no commit was created** |
| Completed phases | **Phase 0 only** — `docs/rag/v3/RAG_V3_PHASE_0_BASELINE.md` (acceptance PASS) |
| Active phase | none — stopped at the V3 §22 human-decision boundary |
| Uncommitted files | 16 entries: the frontend renovation from the earlier session (12 modified, 2 new test files, 1 docs tree) **plus** `docs/rag/v3/` (3 new files). **No RAG application file is modified.** |

## Tests already run — exact outcomes

| Command | Result |
|---|---|
| `python -m ruff check .` | exit 0 |
| `python -m ruff format --check .` | exit 0 |
| `python -m mypy src` | exit 0 |
| `lint-imports` | exit 0 |
| `python -m pytest -q` | **exit 0 — 2127 passed, 10 skipped, 0 failed, 748.49 s** |
| `check_lockfile.py` | exit 0 |
| `check_changelog.py` | exit 0 |
| `check_corpus_manifest.py --data-dir data/nctb` | exit 0 |
| `check_corpus_manifest.py --data-dir data/nctb --corpus-dir data/nctb` | **exit 1 — 1598 ≠ 1605** (a finding, not a regression) |
| `content_qa.py report` × 9 | exit 0 × 9, `flagged_chunks=0` each |

Transcript: `docs/rag/v3/evidence/phase0-baseline-gates.log`.

The API suite has **not** been run since Phase 0 ended, because nothing in the API changed.
If you resume and modify `apps/api`, re-run it: a count materially below 2127 means the run did
not complete and must not be read as green.

## Blockers pending (all require a human; none may be guessed)

`D-1` source rights + curriculum-vs-textbook · `D-2` supported scope · `D-3` pilot slice ·
`D-4` a real teacher for `golden-v4` · `D-5` calibration window for citation enforcement ·
`D-6` embedding model / vector store · `D-7` index off worker startup · `D-8` consent +
retention + the absent DPIA.

Also un-answered: **how to handle the uncommitted frontend renovation.** It is currently riding
along on this branch, uncommitted, and must not be bundled into a RAG commit (V3 §17).

## Next safe action

**Bind the evaluation evidence to the corpus** — V3 P0 (`EVAL-02`, `ING-04`), needs no human
decision, is additive, and changes no threshold or serving behaviour:

1. Record `corpus_digest`, `embedder name/dim`, `prompt_version`, and `retrieval_config_version`
   in every evaluation report.
2. Fix `scripts/evaluate_nctb_retrieval.py:284-329` — the report hashes the manifest *before*
   `_update_manifest` rewrites it, so `corpus_manifest_sha256` can never verify. Hash after.
3. Add a gate that fails when a benchmark's corpus fingerprint does not match the corpus in use.
4. Regenerate `retrieval_eval.json` **as its own reviewed corpus-revision change**, never in the
   same commit as a retrieval change it would mask (project rule, `AGENTS.md` §11).
5. Tests for each of the above; then re-run the API suite and the corpus gates on the final diff.

Do **not** start with citation enforcement. V3 §7.2.6 requires measured false-accept /
false-reject rates before promotion, and the benchmark those measurement would use is not yet
bound to the corpus (Phase 0 §1.1).

## Operations explicitly NOT performed

No commit · no push · no PR · no merge · no branch-protection change · no migration · no
database write beyond an isolated throwaway preview DB in `%TEMP%` (created for the earlier
frontend preview, unrelated to RAG) · no deployment · no release · no tag · no provider call ·
no secret read or printed · no threshold, baseline, ratchet or manifest modified · no corpus
artefact regenerated.
