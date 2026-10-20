"""H-07 / AUD-HI-08: the Postgres posture on a real server, not a mock.

``db/session.py`` ships three promises that only a real PostgreSQL can keep:

* ``statement_timeout`` -- a runaway query is cancelled by the server;
* ``lock_timeout`` -- an unbounded lock wait is cancelled instead of pinning a
  pooled connection forever;
* serialization failures (SQLSTATE 40001) are recognised from the *driver's*
  error object and retried by ``run_with_retry``.

The unit-level shape of all three is pinned in
``tests/test_hi_db_posture.py``; this file is the engine-level proof. It runs
only when ``TEST_DATABASE_URL`` is set (the CI postgres job sets it, and a
throwaway ``docker run postgres:16-alpine`` works locally).
"""

from __future__ import annotations

import os
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.session import (
    is_retryable_db_error,
    make_engine,
    make_session_factory,
    run_with_retry,
)

PG_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

# E-02 (R4-wsC): engine-level proof runs only against a real Postgres.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set (Postgres CI job only)"),
]
SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(**overrides) -> Settings:
    base = {"env": "test", "database_url": PG_URL, "jwt_secret": SECRET}
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def pg_engine():
    engine = make_engine(_settings())
    yield engine
    engine.dispose()


def test_statement_timeout_cancels_a_runaway_query(pg_engine) -> None:
    with pg_engine.connect() as conn:
        assert conn.execute(text("SHOW statement_timeout")).scalar_one() == "30s"
    engine = make_engine(_settings(db_statement_timeout_ms=250))
    try:
        with engine.connect() as conn:
            started = time.perf_counter()
            with pytest.raises(DBAPIError) as excinfo:
                conn.execute(text("SELECT pg_sleep(5)"))
            elapsed = time.perf_counter() - started
        assert "statement timeout" in str(excinfo.value).lower()
        assert elapsed < 3.0, f"the server cancelled after {elapsed:.2f}s, expected ~0.25s"
    finally:
        engine.dispose()


def test_lock_timeout_gives_up_on_a_held_row(pg_engine) -> None:
    with pg_engine.begin() as setup:
        setup.execute(text("DROP TABLE IF EXISTS h2_lock_probe"))
        setup.execute(text("CREATE TABLE h2_lock_probe (id int primary key, v int)"))
        setup.execute(text("INSERT INTO h2_lock_probe VALUES (1, 0)"))
    blocker = make_engine(_settings())
    waiter = make_engine(_settings(db_lock_timeout_ms=300))
    try:
        with blocker.connect() as held, waiter.connect() as waiting:
            held.execute(text("SELECT * FROM h2_lock_probe WHERE id = 1 FOR UPDATE"))
            started = time.perf_counter()
            with pytest.raises(DBAPIError) as excinfo:
                waiting.execute(text("UPDATE h2_lock_probe SET v = v + 1 WHERE id = 1"))
            elapsed = time.perf_counter() - started
            assert "lock timeout" in str(excinfo.value).lower()
            assert elapsed < 2.0, f"waited {elapsed:.2f}s for a lock with a 0.3s budget"
            held.rollback()
    finally:
        blocker.dispose()
        waiter.dispose()
        with pg_engine.begin() as cleanup:
            cleanup.execute(text("DROP TABLE IF EXISTS h2_lock_probe"))


def test_serialization_failure_is_recognised_and_retried_on_real_postgres() -> None:
    """A genuine 40001 from two SERIALIZABLE transactions, then a clean retry.

    Attempt 1 reads the row, a *sibling connection* commits a conflicting
    update, and the write fails with "could not serialize access due to
    concurrent update" -- the real driver error, not a fabricated one.
    ``run_with_retry`` must classify it as retryable, roll back, and replay the
    operation, which then succeeds and commits exactly once.
    """
    serializable = make_engine(_settings()).execution_options(isolation_level="SERIALIZABLE")
    factory = make_session_factory(serializable)
    sibling_engine = create_engine(PG_URL)
    with serializable.begin() as setup:
        setup.execute(text("DROP TABLE IF EXISTS h2_serial_probe"))
        setup.execute(text("CREATE TABLE h2_serial_probe (id int primary key, v int)"))
        setup.execute(text("INSERT INTO h2_serial_probe VALUES (1, 10)"))

    attempts: list[str] = []
    seen_error: list[str] = []

    def operation(session):  # noqa: ANN001
        attempts.append("attempt")
        value = session.execute(text("SELECT v FROM h2_serial_probe WHERE id = 1")).scalar_one()
        if len(attempts) == 1:
            with sibling_engine.begin() as other:
                other.execute(text("UPDATE h2_serial_probe SET v = v + 5 WHERE id = 1"))
        try:
            session.execute(
                text("UPDATE h2_serial_probe SET v = :v WHERE id = 1"), {"v": value + 1}
            )
        except DBAPIError as exc:
            seen_error.append(str(exc.orig).split("\n")[0])
            assert is_retryable_db_error(exc), f"40001 not recognised: {exc.orig}"
            raise
        return value

    try:
        result = run_with_retry(operation, session_factory=factory, sleep=lambda _s: None)
        assert len(attempts) == 2, attempts
        assert seen_error and "could not serialize access" in seen_error[0], seen_error
        # The retry committed the second attempt's value exactly once.
        with sibling_engine.connect() as conn:
            final = conn.execute(text("SELECT v FROM h2_serial_probe WHERE id = 1")).scalar_one()
        assert result == 15  # the value the second attempt read
        assert final == 16  # 15 (sibling) then +1 by the retried write
    finally:
        with serializable.begin() as cleanup:
            cleanup.execute(text("DROP TABLE IF EXISTS h2_serial_probe"))
        serializable.dispose()
        sibling_engine.dispose()
