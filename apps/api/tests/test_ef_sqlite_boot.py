"""AUD-EF-01: SQLite boot must survive a concurrent writer (docker smoke flake).

The "Docker build & container smoke" job starts gunicorn with two workers
against a **fresh** SQLite file. Two things then race at boot:

* every worker runs ``Base.metadata.create_all`` (a write transaction), and
* every worker starts the digest/weakness scheduler loops, whose first act is
  to claim a period in ``job_runs`` (another write).

``PRAGMA journal_mode=WAL`` was executed from the per-connection ``connect``
listener. SQLite refuses a journal-mode change while any other connection has a
transaction open and returns ``SQLITE_BUSY`` **immediately** -- the busy handler
(``busy_timeout``) is not consulted for this statement. The failure therefore
surfaced at ``engine.connect()`` time, wrapped by SQLAlchemy as
``OperationalError: database is locked`` (the ``noconnection`` path seen in the
CI traceback), the worker failed to boot, gunicorn's master shut down, and the
job's "Wait for health endpoint" step failed.

The first test reproduces that race with no sleeps and no threads: one raw
connection holds the write lock exactly as a sibling worker's ``create_all``
does, and the engine must still be able to connect. The second test pins the
behaviour that must not regress: on a quiet database the file still ends up in
WAL mode.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import make_engine

# E-02 (R4-wsC): concurrency + WAL boot with real sleeps -- the slow tier.
pytestmark = pytest.mark.integration


def _settings(db_path: Path) -> Settings:
    return Settings(env="test", database_url=f"sqlite:///{db_path.as_posix()}")


def test_engine_connects_while_a_sibling_worker_holds_the_write_lock(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "boot.db"
    holder = sqlite3.connect(db_path)
    try:
        holder.execute("CREATE TABLE t (x integer)")
        holder.commit()
        # Same lock a concurrent worker's create_all/scheduler claim takes.
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO t VALUES (1)")

        engine = make_engine(_settings(db_path))
        try:
            with engine.connect() as conn:
                # Boot must survive the lock: the connection is established and
                # the committed schema is readable. The sibling's INSERT is
                # uncommitted, so 0 is the correct count here; hitting the
                # uncommitted row would mean reading a database that is mid-write.
                assert conn.exec_driver_sql("SELECT count(*) FROM t").scalar() == 0
                assert conn.exec_driver_sql("SELECT 1").scalar() == 1
        finally:
            engine.dispose()
    finally:
        holder.execute("ROLLBACK")
        holder.close()


def test_file_database_still_ends_up_in_wal_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "quiet.db"
    engine = make_engine(_settings(db_path))
    try:
        with engine.connect() as conn:
            mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            assert str(mode).lower() == "wal"
    finally:
        engine.dispose()


# --------------------------------------------------------------------------
# AUD-EF-01 (second face): "database schema has changed" at boot
# --------------------------------------------------------------------------
def test_safe_init_db_retries_a_sibling_schema_race(monkeypatch) -> None:
    """A DDL invalidated by a sibling worker's CREATE is retried, not fatal.

    The docker smoke died with ``sqlite3.OperationalError: database schema has
    changed`` after the WAL fix removed the "database is locked" variant: the
    same two-worker boot race, different timing. Two failures then success --
    the retry must absorb them, sleeping only between attempts.
    """
    from bangla_gpt_api.initialize import dependencies

    calls = {"n": 0}

    def flaky(_engine) -> None:  # noqa: ANN001 - test double
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("(sqlite3.OperationalError) database schema has changed")

    monkeypatch.setattr(dependencies, "init_db", flaky)
    monkeypatch.setattr(dependencies.time, "sleep", lambda _s: None)
    dependencies._safe_init_db(object(), None)
    assert calls["n"] == 3


def test_safe_init_db_does_not_swallow_other_errors(monkeypatch) -> None:
    """Only the known race signatures are retried; anything else surfaces."""
    import pytest

    from bangla_gpt_api.initialize import dependencies

    def broken(_engine) -> None:  # noqa: ANN001 - test double
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(dependencies, "init_db", broken)
    monkeypatch.setattr(dependencies.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="disk I/O error"):
        dependencies._safe_init_db(object(), None)


def test_safe_init_db_treats_already_exists_as_success(monkeypatch) -> None:
    """The losing worker's "already exists" means the winner created it."""
    from bangla_gpt_api.initialize import dependencies

    def created_by_sibling(_engine) -> None:  # noqa: ANN001 - test double
        raise RuntimeError("(sqlite3.OperationalError) table users already exists")

    monkeypatch.setattr(dependencies, "init_db", created_by_sibling)
    dependencies._safe_init_db(object(), None)
