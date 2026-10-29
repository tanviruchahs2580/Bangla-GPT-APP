# Archive — superseded point-in-time reports

These snapshots were written during earlier milestones and
contradict each other and the current tree (e.g. some predate the circuit
breaker, the router split, MFA and the usage ledger). They are kept for
history only — **do not quote them as current status**.

**Every file carries its own banner.** All 57 report files under
`docs/archive/` open with a "historical, not current" or "archived —
superseded" line: nothing here describes current state, and no file here may
be cited as a source of truth. `scripts/check_archive_banners.py` re-checks
that property on every run, so a file cannot lose its banner silently.

**Ratings and gate claims are self-assessed.** The "x/10" tables and
"CI green" lines in some reports were written by the session that produced
them, not by `score.py` against the findings register; where a claim carries
no evidence id, treat it as an assertion, not a measurement.

Current sources of truth live one level up (living docs):

- `../architecture.md` — verified decisions + pending items
- `../API.md` — hand-written endpoint reference for the surface it covers
  (the generated `../route_baseline.md` and the live `/openapi.json` are the
  full route list)
- `../runbook.md` — operations runbook
- `../qa/QA_REPORT_2026-10-29.md` — the single current QA record
- `QA_REPORT_2026-10-27.md` — superseded 2026-10-29 by the record above
  (this pointer is updated when a record is rotated into the archive; if the
  path does not resolve, read `../qa/` directly rather than trusting a name
  here)

Point-in-time session and audit reports belong in this directory — never
beside the living docs, and never promoted as a source of truth. The
2026-10-16 audit set is archived here as
[`2026-10-16-full-audit/`](2026-10-16-full-audit/) with its own banner README
listing the statements in it that a reader should not act on. The QA records
this directory holds as `qa-audit-<date>.md` are superseded snapshots: they
describe the tree as it was, so their counts and their `docs/qa/…` links are
historical, not current.
