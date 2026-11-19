# T-90 summary — fresh-clone verification

Clone: `git clone --branch remediation/0.2.0` → fresh HEAD `ef524c6…` (then pulled to `0142c46` for the gate repair). NO caches or state reused — fresh venv from `pip install --require-hashes -r constraints.txt`, fresh `npm ci`.

## API gates (fresh clone)
- ruff check: PASS · ruff format --check: 457 files PASS · mypy src: 144 files PASS · check_lockfile: 34 deps PASS
- check_changelog: FAILED first (4 docs commits uncovered) → fixed by regenerating (`9b7faf6`) → PASS ("accounts for all 821 commits")
- Full suite with coverage (CI flags, seeded): **2568 passed / 6 FAILED / 20 skipped** (48.5 min) → coverage floors **36/36, global 89.47% ≥ 89** (the T-16 ratchet held on a fresh clone)
- The 6 failures were ONE root cause: the H-04 FK-policy invariant pinned models FK tables to the frozen a3c5e7f9b1d3 map, but T-20's `short_test_attempt_links` declares its policies in its OWN revision (Q-10). **Fixed under this task** (commit `92b6047`): the invariant now scans later revisions for co-located ondelete declarations; erasure seed list covers the new table. Re-verified on the pulled fresh clone: **219 passed** across fk-policy + attempt-links + classification + authz-matrix.
- Web: `npm ci` PASS (after a disk-space ENOSPC cleared by removing session artifacts — 2.5 GB), lint PASS, build PASS (52.6 s)

## README-only compliance
Every command followed the README/AGENTS.md documented forms; no step needed knowledge outside the docs (the one environment reality: Windows needs the `node npm-cli.js` invocation form, recorded in STATE.md).

## Session artifact cleanup
`bgpt-base-check` worktree removed; load-target uvicorn stopped; disposable containers stopped; coverage artifacts deleted from the clone.
