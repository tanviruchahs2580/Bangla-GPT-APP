# 2026-10-16 full audit — historical record

This directory is a **point-in-time record of the repository as it stood on
2026-10-16**. It was written during one audit-and-remediation session and moved
here (from `docs/audit-2026-10-16/`) so that living documentation keeps exactly
one current QA record.

**It is not current state and must not be quoted as current state.** Read it as
history: what the session found, what it changed, and what it left open. For
today's status use `docs/qa/` (the current QA record), `docs/runbook.md` and
the living docs indexed by `docs/README.md`.

## Corrections a reader would otherwise act on

The reports below were left verbatim (history is not rewritten). Where a
statement inside them is no longer true and someone might act on it, the
correction is recorded here instead:

- **`AUDIT_FINDINGS.md` F-12 / `AUDIT_SUMMARY.md` P1 blocker /
  `RELEASE_READINESS.md` / `SECURITY_REVIEW.md` / `AUDIT_TRACEABILITY_MATRIX.csv`
  R1 — "Android wrapper/assets untracked, APK not buildable from a clean
  clone".** The files (`gradle-wrapper.jar`, launcher/splash assets,
  `data_extraction_rules.xml`) are tracked in git now; the blocker as stated is
  resolved.
- **`AUDIT_FINDINGS.md` F-26 / `UI_UX_ANTI_SLOP_REVIEW.md` — "only class 6 has
  corpus content".** The bundled sample corpus covers classes 6–10.
- **`AUDIT_SUMMARY.md` — "API 828 passed / 6 skipped, web 162 passed".** This
  is the first session's snapshot; the later report in this same directory
  (`LIVE_VERIFICATION_AND_DEPLOY_REPORT.md`) records 950 passed / 6 skipped /
  1 failed and 183 web tests. Neither number describes the tree today.
- **`RELEASE_READINESS.md` / `AUDIT_SUMMARY.md` — "NOT RELEASE-READY
  (NO-GO)".** Superseded within the same session: the work was merged and
  released (`LIVE_VERIFICATION_AND_DEPLOY_REPORT.md`).
- **`AUDIT_SUMMARY.md` — findings totals "33 / 9 fixed / 24 open".** Stale
  even at the time: the addendum in `AUDIT_FINDINGS.md` adds F-34…F-41.
- **`TEST_AND_CI_REPORT.md` / `AUDIT_SUMMARY.md` etc. — "logs/",
  "screenshots/", "38 screenshots", "14 sanitized logs".** Those evidence
  paths were never committed and do not exist in the repository.
- **`AUDIT_SUMMARY.md` — "This audit folder itself is new and untracked".** It
  is committed.

## Contents

10 markdown reports + 2 CSV matrices + 5 probe scripts (`probes/`). See
`docs/archive/README.md` for the archive's own rules.
