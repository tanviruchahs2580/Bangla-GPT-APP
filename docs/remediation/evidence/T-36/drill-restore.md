# T-36 local restore drill — DRILL-ONLY (LOCAL, labeled)

Executed 2026-11-20 on the disposable PostgreSQL 16 container (`bgpt-t21-pg`, tmpfs, throwaway). Real backups and production data were NOT touched (card Never; HO-6 owns the real-infra verification).

1. **Schema**: disposable `pgvector/pgvector:pg16` container upgraded to head (incl. the T-20 revision e2f3a4b5c6d7), one seeded drill table.
2. **Backup**: `pg_dump -U bgpt_t21 -d bgpt_t21 -f /tmp/full.sql` inside the container → **112,021 bytes** (plain SQL; the repo's `scripts/pg_backup.sh` uses custom-format gzip for real use — the restore path is what this drill exercises).
3. **Restore**: fresh `bgpt_t36_restore`; `psql -f /tmp/full.sql` → completed, **48 public tables** (42 domain tables + alembic bookkeeping + the T-20 link table + the drill table), seeded row recovered verbatim.
4. **Drift check**: `alembic check` against the RESTORED database → **"No new upgrade operations detected"** (exit 0).
5. **Timings**: dump/restore ~1 s at this scale — drill artifact only, NEVER an RPO/RTO claim (docs/backup_dr.md states the design targets; the live-topology caveat stands).

## Rollback drill (shared with EG-3)
Migration rollback on seeded data was verified during T-00 and re-verified for the T-20 revision: full-chain `upgrade head → downgrade → upgrade` on SQLite AND PostgreSQL 16 (`evidence/T-20/t20-*-cycle*.txt`).

## Unverifiable here (HO-6)
Real pgBackRest repository restore, backup-schedule verification, cross-region durability, production-scale restore timing, and the live SQLite-topology decision (AGENTS.md §15: the live service runs SQLite while backup_dr.md describes the Postgres design) remain human-owned.
