# ADR-0011: Data and artifact management (git, LFS/DVC, release assets, object storage)

Status: Accepted (2026-10-18). Recorded as a standalone file by the audit
round that raised finding AUD-JK-11/K-05; the consolidated log
`docs/adr/ADRs.md` covers ADR-0001..0010. Template and tone follow that log.

## Context

The repository is public and carries four classes of large or sensitive
artifact:

1. **Copyrighted NCTB corpus text** — `data/nctb/{raw,extracted,normalized}`
   (18 MB on this machine, measured 2026-10-18). Redistribution rights are not
   documented; this is the project's biggest launch blocker
   (`docs/LAUNCH_READINESS_CHECKLIST.md` §3).
2. **Provenance and quality artifacts** — committed facts about the corpus:
   `data/nctb/manifests/acquisition_manifest.jsonl` (9 acquired records with
   sha256 + size), `data/nctb/quality_report.json` (868/879 usable pages, 800
   chunks) and `data/nctb/retrieval_eval.json` (the retrieval baseline the
   RAG doc quotes as the record of truth).
3. **UI evidence screenshots** — 74 tracked PNGs, 12.7 MB on disk, under
   `docs/uiux_renovation_evidence/` (largest single file ~753 KiB).
4. **Evaluation fixtures** — `apps/api/eval/*.json` (golden 634-item baseline,
   red-team set, generated reports), which must stay in lock-step with the
   code that reads them.

Measured repository facts at `0b7dfe6`: the git object database is 41.32 MiB
(`git count-objects -vH`), the largest blob ever committed is the historic
`apps/api/dev.db.bak-wave2` at 1,363,968 bytes (audit finding AUD-JK-04), and
no tracked file exceeds 1 MB in the current tree. There is no LFS
configuration, no DVC, and CI's `actions/checkout` does not fetch LFS content.
An S3 corpus sync helper exists (`scripts/s3_corpus_sync.py`) for the
deployment path.

Constraints that bound the decision:

- The public repo must not redistribute copyrighted textbook text.
- The audit authorisation forbids history rewrites, so the historic DB blob
  cannot be purged in this round (recorded instead: AUD-JK-04, owner action).
- Deployment supplies the corpus out-of-band via `NCTB_CORPUS_DIR`; the
  bundled fallback is a 78-chunk sample.
- Exactly reproducible retrieval numbers depend on the committed eval
  artifacts, not on the corpus text.

## Decision

Keep the current split, and make it explicit and enforced rather than
incidental:

- **In git**: provenance and result artifacts only — the acquisition manifest,
  quality report, retrieval evaluation, and the evaluation fixtures under
  `apps/api/eval/`. These are small (KB), diffable, and cited by name from
  documentation and tests.
- **Not in git**: the corpus itself (`raw/`, `extracted/`, `normalized/`,
  gitignored), any database file (`*.db`, gitignored, plus the historic blob
  under R1 below), and generated QA reports.
- **Out-of-band distribution**: the corpus travels to a deployment through
  the operator (or `scripts/s3_corpus_sync.py` to a bucket); the application
  consumes it via `NCTB_CORPUS_DIR`.
- **Screenshots**: stay committed under `docs/uiux_renovation_evidence/`,
  with a README justifying the set and naming the policy (added with this
  ADR); they are UI evidence that must be readable in a review, and 12.7 MB
  across 74 files is within the range GitHub serves well.
- **Rejected for now**: Git LFS (adds a client requirement and CI checkout
  complexity for a file class that is either small or should not be in git at
  all), DVC (an extra service-like dependency for a single-machine pipeline),
  GitHub release assets (would break the doc/test citations that reference
  committed artifact paths and add a network dependency to tests).

## Alternatives considered

| Option | Why not now |
|---|---|
| Git LFS for the corpus and screenshots | The corpus must not be in the public repo at all; LFS would still publish it. Screenshots are below the threshold where LFS pays for the checkout complexity. Revisit if the evidence set grows past ~100 MB. |
| DVC / artifact registry for eval fixtures | The fixtures are small, reviewable text and the correctness argument depends on them moving in the same commit as the code. |
| Release assets for the corpus | Licence position unchanged (still redistribution), plus tests and docs cite in-repo paths; the operator-supplied directory already solves deployment. |
| Purge the historic DB blob from history | History rewrite is not authorised in this round (R1); recorded as an owner decision with a rotation alternative. |

## Consequences

- A fresh clone runs the API against the 78-chunk sample and says so loudly
  (boot warning + `bgpt_rag_index_chunks{corpus}` metric); building the real
  corpus requires the acquisition step and network access to the official
  NCTB links (`docs/NCTB_DATA_PIPELINE.md` §6, README quick start).
- Retrieval and evaluation numbers are reproducible from committed artifacts
  without the copyrighted text.
- Deleting or regenerating a corpus-derived artifact is a reviewable diff;
  changing the raw corpus is not possible for an outside reader, so every
  cited metric must state its artifact and measurement date.
- Budget: the tracked PNG set is the largest committed binary class (12.7 MB);
  `check-added-large-files --maxkb=512` in `.pre-commit-config.yaml` bounds
  new files but does not retro-fit the existing 74 (largest ~753 KiB).

## Follow-up / owner items

- R1: decide on the historic `dev.db.bak-wave2` blob (notice or scrub) —
  owner action, rewrite not authorised.
- R2: document NCTB redistribution rights — the decision above keeps the text
  out of git, but serving it to students still needs permission.
- R3: if the evidence set grows past ~100 MB, re-open the LFS question with a
  measured size budget (none exists today).
