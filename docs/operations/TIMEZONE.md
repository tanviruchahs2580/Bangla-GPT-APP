# Timezone posture: UTC storage, the clock seam, Dhaka presentation

> Status: **shipped**. The session pin (AUD-HI-02), the column migration to
> ``timestamptz`` (H-14, alembic ``b5d7f9a1c3e5``) and the injectable clock
> seam (``db/clock.py``) are in the tree and verified on SQLite and on
> PostgreSQL 16 (evidence ``E-R2-h2-001``/``E-R2-h2-002``, ``E-R2-h2-004``).
> The one deliberate remainder is the router-side aware-datetime cleanup,
> which is independent and tracked as AUD-EF-16.

## 1. The contract

| Layer | Type | Rationale |
|---|---|---|
| Application code (Python) | naive UTC ``datetime`` | The house contract everywhere (``db/models._utcnow``, ``jobs._utc_naive_now``, ~30 ``.replace(tzinfo=None)`` sites in routers, PDF/export formatters). |
| Database (PostgreSQL) | ``timestamptz`` (UTC) | The stored instant is unambiguous to any reader: ``psql``, BI, a dump restored on another host, ``now()`` comparisons. |
| Database (SQLite) | ISO-8601 text, UTC wall clock | SQLite has no timestamp type; its date functions are UTC. |
| Display | ``Asia/Dhaka`` (UTC+6, no DST) | ``services/activity.dhaka_date`` / ``now_dhaka`` for day boundaries (streaks, heatmap, digest hour). |

``db/types.py::UtcDateTime`` implements the bridge: on PostgreSQL it binds an
aware UTC value (a naive value is *defined* to be UTC) and returns naive UTC,
so the existing call sites keep working; the column itself is ``timestamptz``.
On SQLite the value is stored as naive ISO text, exactly as before.

## 2. What the migration does

``alembic/versions/b5d7f9a1c3e5_h2_timestamptz.py`` converts all 58 timestamp
columns in 38 tables:

```sql
ALTER TABLE t ALTER COLUMN created_at TYPE timestamptz
  USING created_at AT TIME ZONE 'UTC';
```

* ``AT TIME ZONE 'UTC'`` is correct because every writing session has been
  pinned to UTC since AUD-HI-02 (``db/session.py``: ``-c timezone=utc``); the
  stored values already denote UTC wall-clock readings.
* **Downgrade** applies the inverse expression, so the expansion is reversible
  while the session pin is in force (removing the pin first would break the
  rollback — do not).
* **SQLite** is a deliberate no-op in both directions: the type name carries no
  semantics there, and rebuilding 38 tables to change an inert string would
  risk far more than it buys.
* **Locking:** PostgreSQL rewrites each table under ``ACCESS EXCLUSIVE``. Run it
  in the deploy window; a table rewrite of this size is seconds for the
  current data volume, but it is not an online operation.
* **Verification:** up → down → up on a fresh SQLite database and on a fresh
  PostgreSQL 16 database, with ``alembic check`` clean after each cycle
  (``E-R2-h2-001``, ``E-R2-h2-002``); the type of ``users.created_at`` /
  ``locked_until`` and a native ``now() - interval`` comparison are asserted in
  ``tests/test_h2_time.py`` (``E-R2-h2-004``).

## 3. The injectable clock (``db/clock.py``)

* ``utcnow()`` -> naive UTC through the seam (the shape the code expects);
  ``Clock.now_aware()`` -> the same instant with tzinfo.
* Production reads ``SystemClock``; tests install ``FrozenClock`` with
  ``set_clock`` and remove it with ``reset_clock`` (``tests/conftest.py`` also
  resets it after every test).
* Callers migrated in this round: ``services/retention.py`` and
  ``services/parent_digest.py``. The bulk migration of the remaining ~90 direct
  ``datetime.now`` sites belongs to AUD-EF-16 (an EF-domain finding) and is
  deliberately not bundled here.

## 4. Boundary tests

``tests/test_h2_time.py`` pins, with exact instants:

* the Asia/Dhaka day flip at 18:00 UTC (including the leap-day boundary);
* the digest hour at 16:00 UTC == 22:00 Dhaka, including the second before;
* the retention cutoff being strict (a row exactly on the cutoff survives; a
  microsecond older is swept);
* a write at 00:00:01 Dhaka storing the UTC instant, not a local-wall-clock
  value (read back through a raw SQLite connection).

## 5. Operational notes

* ``DB_STATEMENT_TIMEOUT_MS`` / ``DB_LOCK_TIMEOUT_MS`` and ``timezone=utc``
  travel in the libpq ``options`` string, so the posture applies to every
  pooled connection (H-07; verified against a real server in
  ``tests/test_h2_pg_posture.py``).
* If a future migration adds a timestamp column, declare it
  ``UtcDateTime`` from ``db/types.py`` — a bare ``DateTime`` reintroduces a
  ``timestamp without time zone`` column, and ``alembic check`` in the
  PostgreSQL CI job is what catches it.
