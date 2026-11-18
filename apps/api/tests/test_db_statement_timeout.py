"""Postgres engine posture: statement_timeout rides every pooled connection.

The 2026-11-17 audit (P2) found the engine set a TCP connect timeout and
nothing else: one runaway statement held a pooled connection indefinitely
on the single-host deployment. The bound now travels via the libpq
``options`` connection parameter and is switchable with
POSTGRES_STATEMENT_TIMEOUT_MS (0 = off, for migration-style long DDL on a
dedicated connection). SQLite (dev/CI/live) never receives it.
"""

from unittest.mock import MagicMock

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db import session as db_session

_SECRET = "test-secret-0123456789abcdef0123456789"


@pytest.fixture
def captured_create_engine(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture create_engine kwargs without touching a real server."""
    calls: dict = {}

    def fake_create_engine(url: str, **kwargs: object) -> MagicMock:
        calls["url"] = url
        calls["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr(db_session, "create_engine", fake_create_engine)
    return calls


def _pg_settings(**over: object) -> Settings:
    return Settings(
        env="test",
        database_url="postgresql+psycopg://bgpt:not-a-real-password@localhost:5432/bgpt",
        jwt_secret=_SECRET,
        **over,  # type: ignore[arg-type]
    )


def test_postgres_engine_sets_statement_timeout(captured_create_engine: dict) -> None:
    db_session.make_engine(_pg_settings(postgres_statement_timeout_ms=30000))
    connect_args = captured_create_engine["kwargs"]["connect_args"]
    assert connect_args["options"] == "-c statement_timeout=30000"
    assert connect_args["connect_timeout"] == db_session.POSTGRES_CONNECT_TIMEOUT_SECONDS
    # The rest of the audited pool posture is unchanged.
    kwargs = captured_create_engine["kwargs"]
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_size"] == 10
    assert kwargs["max_overflow"] == 20


def test_postgres_statement_timeout_is_enabled_by_default(
    captured_create_engine: dict,
) -> None:
    db_session.make_engine(_pg_settings())
    connect_args = captured_create_engine["kwargs"]["connect_args"]
    assert connect_args["options"] == "-c statement_timeout=30000"


def test_postgres_statement_timeout_zero_disables(captured_create_engine: dict) -> None:
    db_session.make_engine(_pg_settings(postgres_statement_timeout_ms=0))
    connect_args = captured_create_engine["kwargs"]["connect_args"]
    assert "options" not in connect_args
    assert connect_args["connect_timeout"] == db_session.POSTGRES_CONNECT_TIMEOUT_SECONDS


def test_sqlite_engine_never_receives_postgres_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict = {}

    def fake_create_engine(url: str, **kwargs: object) -> MagicMock:
        calls["url"] = url
        calls["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr(db_session, "create_engine", fake_create_engine)
    # The pragma listener requires a real Engine; the kwargs are what this
    # test pins, so the listener itself is stubbed out.
    monkeypatch.setattr(db_session, "_apply_sqlite_pragmas", lambda engine, url: None)
    db_session.make_engine(
        Settings(env="test", database_url="sqlite:///./t.db", jwt_secret=_SECRET)
    )
    connect_args = calls["kwargs"]["connect_args"]
    assert set(connect_args) == {"check_same_thread"}
