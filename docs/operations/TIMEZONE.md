# Timezone posture and the timestamptz migration plan

> Status: the **session pin is shipped** (this round, AUD-HI-02); the **column
> migration is DEFERRED** with the plan below, because it rewrites every
> timestamp column in a live schema and must be executed as a separately
> reviewed, expand–contract change with an explicit owner go-ahead.

## 1. The defect this addresses

- Every timestamp column in `db/models.py` is a naive `DateTime` → PostgreSQL
  `timestamp without time zone` (`rg 'DateTime\(timezone=True\)'`: 0 hits).
- The application writes **aware UTC** values (`datetime.now(UTC)`) and around
  ten call sites strip the tzinfo (`.replace(tzinfo=None)`) before storing.
- A naive value is interpreted in the **session** timezone. On a host or managed
  database whose default is not UTC, the stored instant silently shifts — and a
  system serving South Asian users will meet such a host eventually.

## 2. What ships now (verified)

`db/session.py` pins every PostgreSQL session through libpq options:

```
connect_args = {"connect_timeout": 10,
                "options": "-c timezone=utc -c statement_timeout=30000 -c lock_timeout=5000"}
```

- `timezone=utc` makes the naive values unambiguously UTC for every pooled
  connection, on any host, without touching a single stored byte.
- Timeouts are configurable: `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS`
  (0 disables a guard; omitted from the options string).
- SQLite needs no equivalent: it has no session timezone, its date functions
  are UTC, and the application always writes UTC values.
- Pinned by `apps/api/tests/test_hi_db_posture.py`.

This is a correctness pin, not the end state: a naive column still cannot
represent an instant unambiguously to an external reader (a BI tool, a
`psql` session, a future service) and it cannot be compared against
`now()` correctly.

## 3. Migration plan (deferred work, in order)

**Preconditions**

1. Owner go-ahead (schema rewrite on a live education system).
2. A staging run against a production-sized dump, with row counts recorded.
3. `pgbackrest` restore point taken immediately before the production step
   (`docs/backup_dr.md`).

**Step 1 — inventory.** Generate the full list of `DateTime` columns and their
tables (`db/models.py` is the source; the alembic head is the comparison). Every
column gets a decision: convert, or justify keeping naive. Do not proceed with
an incomplete list.

**Step 2 — expand.** One alembic revision per table group, each:

```sql
ALTER TABLE t
  ALTER COLUMN created_at TYPE timestamptz
  USING created_at AT TIME ZONE 'UTC';
```

`AT TIME ZONE 'UTC'` is correct **only** because §2 pins the writing sessions
to UTC. Run against a staging dump first and compare a sample of instants
before/after to prove no shift.

**Step 3 — code.** Flip the models to `DateTime(timezone=True)`, remove the 30
`.replace(tzinfo=None)` call sites, and let SQLAlchemy pass aware values.
Grep for `_utcnow`, `now(UTC)`, `isoformat(sep=" ")` and the strip sites; each
is either removed or documented as a boundary (for example an HTTP header
formatting site).

**Step 4 — contract.** After a full deploy of step 3 has been stable for one
release, drop nothing (Postgres does not need it) and keep the `AT TIME ZONE`
defaults out of the way. The migration is complete when
`rg 'DateTime\(' apps/api/src` matches only `timezone=True` columns plus
documented exceptions.

**Step 5 — tests.** A `test_*_timestamptz.py` that asserts, on the SQLite test
database, that a freshly written row round-trips as an aware UTC datetime, plus
a Postgres-marked integration test in CI's postgres job.

**Rollback.** Each expand step is reversible with the inverse
`USING created_at AT TIME ZONE 'UTC'` — *only* while the pins of §2 are still
in force. Both this document and the alembic revisions must say so; removing
the session pin before step 4 completes would break the rollback.

## 4. Why this is not in this round

The change touches 41 tables (`grep -c '^class .*(Base):' db/models.py`), 59
`DateTime` column declarations, and 30 `.replace(tzinfo=None)` sites across the
routers (`rg 'replace\(tzinfo=None\)' apps/api/src`: 30 hits), plus the export
paths and the PDF/notification formatters. Shipping it without a staging
rehearsal against real data would trade a silent-shift risk for a loud-corruption
risk. The session pin removes the *actual* failure mode the audit found (a
non-UTC server storing shifted timestamps) today; the column rewrite is filed
as its own issue with this plan attached.
