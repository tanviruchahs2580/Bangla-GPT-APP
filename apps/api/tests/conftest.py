"""Hermetic test configuration.

Two layers of isolation:

1. Module (import) time — applied *before* test collection. ``main.py`` builds
   a module-level ``app = create_app`` for gunicorn, and test modules import
   it during collection, before any fixture runs. Without the import-time patch
   here, that collection-time build would use the real default (a file SQLite
   store) and pollute the workspace; CI's later ``alembic upgrade head`` then
   fails against the half-created schema (``table users already exists``).

2. Per test — the autouse fixture re-applies the patch and clears any
   config-named OS environment variables.

Developers may keep a real ``.env`` beside the compose stack; unit tests must
never inherit values from it. pydantic-settings resolves ``env_file`` relative
to the current working directory, and in v2 it captures the config at
class-creation time — patching ``Settings.model_config`` alone does NOT
disable loading, so we force ``_env_file=None`` through ``__init__`` too.

The default ``database_url`` is a file-based SQLite store (for local dev
persistence), which tests must never touch: tests that do not pass an
explicit ``database_url`` (kwarg or env) get an in-memory database, so
every run stays hermetic and never shares ``./bangla_gpt.db``.
"""

import os

import pytest

from bangla_gpt_api.config import Settings

_ORIG_MODEL_CONFIG = dict(Settings.model_config)
_ORIG_INIT = Settings.__init__

_HERMETIC_MODEL_CONFIG = dict(_ORIG_MODEL_CONFIG)
_HERMETIC_MODEL_CONFIG["env_file"] = None

# Opt-in: run the domain suite against a real PostgreSQL database.
# `BGPT_TEST_DATABASE_URL` (deliberately NOT a Settings field, so the
# per-test env scrub below cannot remove it) switches every test that uses
# the default hermetic database to this URL, with table truncation between
# tests for isolation. The postgres CI job sets it so the production engine
# runs the same domain suite SQLite runs -- catching engine-specific drift
# (JSON/boolean/UPSERT/transaction semantics) that a SQLite-only suite
# cannot see. Tests that pass an explicit database_url (engine-specific
# tests) keep their engine either way.
_PG_TEST_URL = os.environ.get("BGPT_TEST_DATABASE_URL", "").strip()

_pg_engine = None


def _hermetic_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
    kwargs["_env_file"] = None
    # Explicit kwargs/env still win (pydantic-settings precedence); only the
    # default is replaced, so tests never share ./bangla_gpt.db.
    if "database_url" not in kwargs and "DATABASE_URL" not in os.environ:
        kwargs["database_url"] = _PG_TEST_URL or "sqlite://"
    return _ORIG_INIT(self, *args, **kwargs)


# Layer 1: active before any test module import during collection.
Settings.model_config = _HERMETIC_MODEL_CONFIG  # type: ignore[misc]
Settings.__init__ = _hermetic_init  # type: ignore[method-assign]


def engine_url(tmp_path, name: str) -> str:  # type: ignore[no-untyped-def]
    """Resolve a test database URL for tests that pin their own database.

    The audit (H-02) found 102 of 137 test files pinning
    ``sqlite:///{tmp_path}/...`` directly, so the "engine parity" CI job ran
    ~27% of the suite on Postgres while its name claimed all of it. Tests
    that resolve through this helper run on the parity engine when
    ``BGPT_TEST_DATABASE_URL`` is set (the autouse truncation fixture below
    provides the isolation the per-file database used to), and keep the
    historical per-file SQLite store otherwise. ``name`` preserves the old
    per-file naming on SQLite so parallel-variant tests stay distinguishable
    in failure output; on Postgres every name resolves to the one shared
    database. (``name`` may carry its own ``.db`` suffix -- both conventions
    exist among the converted call sites.)
    """
    if not name.endswith(".db"):
        name = f"{name}.db"
    return _PG_TEST_URL or f"sqlite:///{tmp_path}/{name}"


@pytest.fixture(autouse=True)
def _isolate_production_opt_ins():
    """Stop production-guard opt-ins leaking between tests.

    Some tests build a production Settings object to exercise other production
    behaviour (metrics gating, the PII key guard, docs exposure) while using
    the mock provider and an in-process SQLite database. They declare that with
    ALLOW_MOCK_LLM_IN_PRODUCTION and WEB_CONCURRENCY, which the 2026-10-09
    guards otherwise refuse. Without this cleanup those variables persist for
    the rest of the session and silently disable the guards under test.

    This only isolates tests. It does not weaken enforce_production_safety.
    """
    yield
    os.environ.pop("ALLOW_MOCK_LLM_IN_PRODUCTION", None)
    os.environ.pop("WEB_CONCURRENCY", None)


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    # Layer 2: re-assert the patch for the duration of each test and scrub
    # process environment so no config value leaks in from the runner.
    monkeypatch.setattr(Settings, "model_config", dict(_HERMETIC_MODEL_CONFIG))
    monkeypatch.setattr(Settings, "__init__", _hermetic_init)
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)


@pytest.fixture(autouse=True)
def _pg_test_isolation():
    """Truncate every table after each test when running on PostgreSQL.

    The default hermetic database is per-engine in-memory SQLite, which is
    isolated by construction. A shared PostgreSQL database is not: without
    cleanup, a test's committed rows (users, schools, conversations) leak
    into the next test and produce order-dependent failures -- the reason a
    full-suite PG run was previously impossible rather than merely absent.
    Truncation runs after the test so a failing test's data is still
    inspectable in the failure output; RESTART IDENTITY keeps id-based
    assertions deterministic, and CASCADE follows the FK graph in one
    statement.
    """
    yield
    if not _PG_TEST_URL:
        return
    global _pg_engine
    from sqlalchemy import create_engine
    from sqlalchemy.exc import ProgrammingError

    from bangla_gpt_api.db.base import Base

    if _pg_engine is None:
        _pg_engine = create_engine(_PG_TEST_URL)
    table_names = ", ".join(sorted(Base.metadata.tables))
    try:
        with _pg_engine.begin() as conn:
            conn.exec_driver_sql(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE")
    except ProgrammingError:
        # Schema not created yet (first test that builds the app does it);
        # nothing to clean in that case.
        pass
