"""H-04/H-14 and H-07: Postgres session posture and serialization retries.

Pins the two guarantees this round adds to ``db/session.py``:

* every Postgres session is pinned to UTC (naive ``DateTime`` columns are
  otherwise interpreted in the server's session timezone) and carries a
  statement and lock timeout, so a runaway query cannot hold a pooled
  connection forever;
* serialization failures and deadlocks (SQLSTATE 40001/40P01) are retried,
  bounded and jittered, and nothing else is.
"""

import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db import session as session_module


def _settings(tmp_path, url: str, **overrides) -> Settings:
    base = {
        "env": "test",
        "database_url": url,
        "jwt_secret": "test-secret-0123456789abcdef0123456789",
        "admin_email": "root@example.com",
        "admin_password": "supersecret1",
        "force_admin_password_change": False,
    }
    base.update(overrides)
    return Settings(**base)


class _PgError(Exception):
    """A minimal psycopg-shaped error carrying a SQLSTATE."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"pg error {sqlstate}")
        self.sqlstate = sqlstate


def test_postgres_connect_args_pin_utc_and_timeouts(monkeypatch) -> None:
    captured: dict = {}
    real_create_engine = session_module.create_engine

    def spy(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return real_create_engine("sqlite://", connect_args={"check_same_thread": False})

    monkeypatch.setattr(session_module, "create_engine", spy)
    settings = _settings(
        None,
        "postgresql+psycopg://bgpt:bgpt@localhost:5432/bgpt",
        db_statement_timeout_ms=12_000,
        db_lock_timeout_ms=3_000,
    )
    session_module.make_engine(settings)

    connect_args = captured["kwargs"]["connect_args"]
    assert connect_args["connect_timeout"] == session_module.POSTGRES_CONNECT_TIMEOUT_SECONDS
    options = connect_args["options"]
    assert "-c timezone=utc" in options
    assert "-c statement_timeout=12000" in options
    assert "-c lock_timeout=3000" in options
    # Pool posture unchanged.
    assert captured["kwargs"]["pool_pre_ping"] is True
    assert captured["kwargs"]["pool_size"] == 10


def test_timeout_guards_are_omitted_when_disabled() -> None:
    settings = _settings(
        None,
        "postgresql+psycopg://bgpt:bgpt@localhost:5432/bgpt",
        db_statement_timeout_ms=0,
        db_lock_timeout_ms=0,
    )
    options = session_module.postgres_session_options(settings)
    assert options == "-c timezone=utc"


def test_sqlite_engine_is_not_given_postgres_options(tmp_path, monkeypatch) -> None:
    captured: dict = {}
    real_create_engine = session_module.create_engine

    def spy(url, **kwargs):
        captured["kwargs"] = kwargs
        return real_create_engine(url, **kwargs)

    monkeypatch.setattr(session_module, "create_engine", spy)
    engine = session_module.make_engine(_settings(tmp_path, f"sqlite:///{tmp_path}/hi.db"))
    assert "options" not in captured["kwargs"].get("connect_args", {})
    # The UTC contract on SQLite comes from the code writing UTC values and
    # SQLite's own UTC timestamp functions; assert the pin is not silently
    # half-applied through a driver option that SQLite would reject.
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1


def test_is_retryable_db_error_covers_40001_and_40p01() -> None:
    assert session_module.is_retryable_db_error(DBAPIError("s", {}, _PgError("40001")))
    assert session_module.is_retryable_db_error(DBAPIError("s", {}, _PgError("40P01")))
    # A unique-violation or a syntax error must never be retried.
    assert not session_module.is_retryable_db_error(DBAPIError("s", {}, _PgError("23505")))
    assert not session_module.is_retryable_db_error(sqlite3.OperationalError("database is locked"))


def test_is_retryable_reads_psycopg_diag(tmp_path) -> None:
    class _Diag:
        sqlstate = "40001"

    class _WithDiag(Exception):
        diag = _Diag()

    assert session_module.is_retryable_db_error(DBAPIError("s", {}, _WithDiag()))


def test_run_with_retry_retries_serialization_failure_then_succeeds(tmp_path) -> None:
    settings = _settings(tmp_path, f"sqlite:///{tmp_path}/retry.db")
    engine = session_module.make_engine(settings)
    session_module.init_db(engine)
    factory = session_module.make_session_factory(engine)

    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky(session):
        calls["n"] += 1
        if calls["n"] < 3:
            raise DBAPIError("INSERT", {}, _PgError("40001"))
        session.execute(text("CREATE TABLE IF NOT EXISTS hi_retry (id INTEGER)"))
        session.execute(text("INSERT INTO hi_retry (id) VALUES (1)"))
        return "ok"

    result = session_module.run_with_retry(flaky, session_factory=factory, sleep=sleeps.append)
    assert result == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM hi_retry")).scalar_one() == 1


def test_run_with_retry_does_not_retry_other_errors(tmp_path) -> None:
    settings = _settings(tmp_path, f"sqlite:///{tmp_path}/retry2.db")
    engine = session_module.make_engine(settings)
    session_module.init_db(engine)
    factory = session_module.make_session_factory(engine)

    calls = {"n": 0}

    def broken(session):
        calls["n"] += 1
        raise DBAPIError("INSERT", {}, _PgError("23505"))

    with pytest.raises(DBAPIError):
        session_module.run_with_retry(broken, session_factory=factory, sleep=lambda _: None)
    assert calls["n"] == 1


def test_run_with_retry_gives_up_after_attempts(tmp_path) -> None:
    settings = _settings(tmp_path, f"sqlite:///{tmp_path}/retry3.db")
    engine = session_module.make_engine(settings)
    session_module.init_db(engine)
    factory = session_module.make_session_factory(engine)

    calls = {"n": 0}

    def always_conflict(session):
        calls["n"] += 1
        raise DBAPIError("UPDATE", {}, _PgError("40P01"))

    with pytest.raises(DBAPIError):
        session_module.run_with_retry(
            always_conflict, session_factory=factory, attempts=3, sleep=lambda _: None
        )
    assert calls["n"] == 3
