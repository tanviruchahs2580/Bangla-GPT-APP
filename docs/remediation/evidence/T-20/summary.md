# T-20 summary — link tables for JSON-array attempt membership (BC-5)

Executed 2026-11-20 (branch `remediation/0.2.0`).

## Discovery that shaped the design
`assignments` ALREADY have their indexed mirror: `assignment_recipients` (migration `c5d7e9f1a3b5` — created, indexed, backfilled from the JSON, dual-written in `teacher_assignment_create`). Building a second assignment link table would have been a duplicate. The genuine gap is **short_tests** (`short_tests.attempts` JSON, scanned by membership at assessment.py:274 and serialized at :106).

## What was built
1. **Model**: `ShortTestAttemptLink` (`short_test_attempt_links`, unique (short_test_id, student_id), FKs CASCADE, 3 indexes) — models.py.
2. **Migration** `e2f3a4b5c6d7`: creates the table + backfills from the JSON history (idempotent, conflict-ignoring, batched per 200 parent ids, dialect-conditional ON CONFLICT/IGNORE); downgrade drops the mirror only — the JSON source data is never modified. Cycle verified on SQLite (`t20-migration-cycle-sqlite.txt`) and **PostgreSQL 16** (`t20-migration-cycle-postgres.txt`, re-verified after the final edits: `t20-pg-cycle-final.txt`).
3. **Dual-write**: `teacher_shorttest_create` calls `sync_attempt_links` in the same transaction as the JSON write (`services/attempt_links.py`).
4. **Read switch** `ATTEMPT_LINKS_READ` (default False = JSON read path, Q-18, documented in `.env.example`): `attempt_refs` returns the identical `[(student_id, attempt_id)]` shape from either store; wired into short-test serialization, mine-lookup, assignment serialization, and assignment progress rows. Assignments read the EXISTING `assignment_recipients` under the flag.
5. **Reconciliation**: `reconcile_attempt_links` (count + set equality per parent) — the gate that must pass before the JSON default flips (S-3) and the JSON column drops (later release).

## Evidence
- `tests/test_attempt_link_tables.py` (4 tests): dual-write mirror equality; read on/off identical API responses; assignment dual-write uses the existing recipient table; parent deletion cascades link rows.
- Cluster: 32 tests green across attempt-links/bulkassign/shorttest/attempt-projection/tenancy suites; `mypy src` 144 files clean; ruff clean.
- EG-3: full-chain up/down/up including the new revision on SQLite and PostgreSQL 16.

## Rollout sequence (recorded for the final report)
deploy → migration adds mirror + backfill → dual-write active (JSON still authoritative for reads) → reconciliation green → [S-3] flip `ATTEMPT_LINKS_READ=true` → later release drops JSON columns. Rollback: flip the flag off; downgrade drops mirror tables (JSON untouched).
