# Evidence index

One row per evidence file. All captures record: command, working directory, base SHA, exit code, duration, output. Never contains secrets or personal data (H-15).

## T-00 (baseline)

| File | Content |
|---|---|
| `T-00/inventory.txt` | Tracked-file inventory, LOC by extension, manifests, workflows, Alembic head, non-NFC Bangla scan |
| `T-00/api-tests-run-1-corrected.txt` | `pytest -q` run 1 — 2314 passed / 20 skipped |
| `T-00/api-tests-run-2.txt` | `pytest -q` run 2 (independent) — identical totals |
| `T-00/api-coverage.txt` | CI-exact coverage run — 89.52%, reports written |
| `T-00/api-coverage-floors-verified.txt` | `check_coverage_floors.py coverage.json` — 36/36 floors met |
| `T-00/api-ruff-check.txt` / `api-ruff-format.txt` / `api-mypy.txt` / `api-lockfile.txt` / `changelog-check.txt` / `corpus-manifest-check.txt` | Gate runs, exit 0 each |
| `T-00/api-import-linter.txt` | exit 127 — tool unavailable locally |
| `T-00/api-migration-cycle-verified2.txt` | Disposable SQLite `upgrade head → downgrade base → upgrade head` — PASS (51 revisions) |
| `T-00/api-alembic-drift-verified2.txt` | `alembic check` after upgrade — no drift |
| `T-00/api-openapi-export-verified2.txt` | OpenAPI export — 121 paths / 140 ops, byte-identical to tracked fixture |
| `T-00/api-route-baseline-resolved.txt` | Resolved runtime route baseline (16 top-level entries, 12 included routers) |
| `T-00/openapi.baseline.json` / `routes.baseline.json` | Baseline artifacts |
| `T-00/api-evaluation-binding-verified2.txt` | Identity binding notice (baseline predates identity) |
| `T-00/api-evaluation-regression-verified2.txt` | Golden v3 regression gate — PASS |
| `T-00/api-evaluation-redteam-verified2.txt` | Red-team — PASS 36/36 |
| `T-00/api-golden-24-verified2.txt` + `golden-24-report.json` | 24-question gate — hit@3 1.0, accuracy 0.9167 |
| `T-00/coverage-run.json` / `coverage-run.xml` | Preserved coverage reports (sha256 recorded in STATE.md) |
| `T-00/web-lint-verified.txt` / `web-format-verified.txt` / `web-deadcode-verified.txt` / `web-build-verified.txt` | Web gates, exit 0 |
| `T-00/web-test-verified2.txt` | 124 files / 592 tests passed |
| `T-00/web-coverage-verified2.txt` | 76.76/70.07/72.27/78.94 — above ratchets |
| `T-00/recorder-smoke.txt` | capture.py smoke test |
| Superseded (do not cite): `api-migration-cycle-full.txt`, `api-alembic-check-sqlite.txt`, `api-migration-cycle-verified.txt`, `api-alembic-drift-verified.txt`, `api-openapi-export-verified.txt`, `api-route-baseline-verified.txt`, `api-evaluation-{binding,regression,redteam,golden-24-verified}.txt`, `api-openapi-smoke.txt`, `api-route-baseline-verified2.txt`, `api-migration-cycle.txt`, `api-tests-run-1.txt`, `web-*-corrected.txt`, `web-build.txt`, `web-deadcode.txt`, `web-format.txt`, `web-lint.txt` | Failed or superseded attempts — retained as honest records; reasons in STATE.md |

## T-01 (findings verification)

| File | Content |
|---|---|
| `T-01/t01-f01-tracked-files.txt` | F-01: tracked `.env`/db/coverage files (zero) + full-history `.env` additions (zero) |
| `T-01/t01-f02-nctb-inventory.txt` | F-02: 5 tracked `data/nctb` metadata files; gitignore lines; repo visibility PUBLIC |
| `T-01/t01-batch-a2.txt` | Batch A: history `.db` scan (1: `dev.db.bak-wave2`), version declarations, router LOC, async-Session handlers, JSON columns, FK ondelete counts, frontend sizes, e2e specs, eval counts, routes-vs-OpenAPI, git process survey |
| `T-01/t01-batch-a.txt`, `t01-f01…` earlier variants | First run aborted on a path bug (parents[2]); superseded by `-a2` |

Note: `[C:]` citations in `FINDINGS_VERIFIED.md` that name inline commands (grep over auth/users/admin files, safety/providers greps, PyPI registry check, OpenAPI path probe) were run directly in the session shell at HEAD `31e3e60` with output quoted in the finding rows; captures for the batchable ones are the files above.
