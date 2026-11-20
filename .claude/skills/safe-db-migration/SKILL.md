---
name: safe-db-migration
description: Create, review or verify an Alembic migration for the Bangla-GPT-APP API safely. Use whenever apps/api db/models.py changes, a table, column, index or constraint is added or altered, a file under apps/api/alembic/versions is written or edited, or anyone asks to run alembic against a database.
---

# Safe database migrations for Bangla GPT

This applies AGENTS.md §6 and §10. The database holds children's records, so a
bad migration is a data-protection incident, not only a bug.

## Rules that do not bend

- Never edit a migration that is already on `main`; add a new revision.
- Keep one head (`alembic heads`). Change `db/models.py` and its migration in
  the same PR. `alembic check` must report no drift.
- SQLAlchemy 2 **sync** only: no async engine or session.
- Run migrations only against a throwaway database. Any other database needs
  the user's explicit approval, naming it (AGENTS.md §14).
- Treat every database as live until the user says otherwise. PostgreSQL is
  the production engine (AGENTS.md §10), but the live API runs **SQLite** today
  (`docs/runbook.md` §7.3), so a migration can touch live children's data.
- Expand–contract is required for zero-downtime deploys (`docs/runbook.md`,
  "Expand–contract convention"):
  - add new columns as nullable, or with a server default;
  - never rename a column: add the new name, backfill it in a separate
    idempotent migration, and retire the old column in a later release;
  - enforce NOT NULL or drop a column only in a later release.
- Autogenerate turns a column rename into a drop plus an add, which destroys the
  column's data. Hand-write the expand step instead.
- Student data: a new table or column that holds student data must be covered
  by the export, the erasure and the retention sweep (AGENTS.md §6). The guards:
  - `tests/test_w2_db_export_completeness.py` derives the export requirement
    from `Base.metadata`;
  - `tests/test_export_completeness.py` checks only a fixed list of section
    names, so it does not prove a new table is exported;
  - `tests/test_round2_erasure_fk.py` is the erasure foreign-key guard;
  - no test I found derives retention-sweep coverage from the schema. Add the
    sweep by hand and say so in the PR.
- Guardian phone numbers and other PII go through `encrypt_pii_strict`;
  single-use tokens are stored as SHA-256 hashes only. Never put PII in a
  migration's output or in fixtures.
- Retention windows, the consent version and the audit-log policy change only
  on explicit instruction.

## Create

Each command runs in a subshell, so the scratch `DATABASE_URL` never leaks into
later commands. `*.db` files are gitignored, and never opened.

```bash
(cd apps/api && export DATABASE_URL=sqlite:///./_migration_scratch.db && rm -f _migration_scratch.db && ../../.venv/Scripts/python.exe -m alembic upgrade head && ../../.venv/Scripts/python.exe -m alembic heads)
```

After editing `src/bangla_gpt_api/db/models.py`:

```bash
(cd apps/api && export DATABASE_URL=sqlite:///./_migration_scratch.db && ../../.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add <thing>")
```

Delete `apps/api/_migration_scratch.db` once the revision is written.

## Review the new revision in apps/api/alembic/versions/ before running it

- Drop autogenerate noise that is not a real change. Check every rename (see
  the rule above).
- SQLite cannot ALTER most things in place. Follow the existing revisions that
  use `op.batch_alter_table`; seven of them do.
- Write `downgrade()` to undo `upgrade()` exactly. CI runs upgrade, then
  downgrade to base, then upgrade again.
- Name constraints explicitly. Avoid SQL that only SQLite accepts.
- Data migrations are idempotent, chunked, and never print row contents.
- Column comments: SQLite's `alembic check` does not compare them (see
  `tests/test_migrations_match_models.py`), so comment drift is caught only by
  the PostgreSQL job in CI.

## Verify: the cycle CI runs

The first command is the migration cycle. It runs `alembic` through the ask
rule, so each step asks for approval. That is expected, because scratch
databases cannot be told apart from live ones by the rule. The second command
runs the migration and schema tests:

```bash
(cd apps/api && export DATABASE_URL=sqlite:///./_ci_scratch.db && rm -f _ci_scratch.db && ../../.venv/Scripts/python.exe -m alembic upgrade head && ../../.venv/Scripts/python.exe -m alembic downgrade base && ../../.venv/Scripts/python.exe -m alembic upgrade head && ../../.venv/Scripts/python.exe -m alembic check; rc=$?; rm -f _ci_scratch.db; echo "migration cycle exit=$rc")
(cd apps/api && ../../.venv/Scripts/python.exe -m pytest -q -p randomly --randomly-seed=20261030 tests/test_migrations_match_models.py tests/test_w2_db_export_completeness.py tests/test_round2_erasure_fk.py tests/test_wave2_data_integrity.py; rc=$?; rm -f bangla_gpt.db; exit $rc)
```

The PostgreSQL leg needs a PostgreSQL server (and Docker to run one). `psql`
is only a client, and this machine has no server. CI runs the same up, down, up
cycle and `alembic check` against PostgreSQL in its postgres job. Report that
leg as "CI only".

## Report

The new revision id and its `down_revision`, what it changes (and whether it
is an expand step), the cycle result and the `alembic check` output, the tests
run with their numbers, and the PostgreSQL leg as "CI only".
