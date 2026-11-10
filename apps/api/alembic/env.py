"""Alembic entry point.

The engine here is built for migrations, not for serving, but it must not run
with a WEAKER SQLite posture than the application: an `alembic upgrade` against
a live single-file deployment used to open its connection with
`busy_timeout=0` and `journal_mode=delete`, so the first write collision with a
running worker raised `database is locked` immediately (SQLITE_BUSY) and could
fail a deploy that the 15s busy timeout exists to absorb, while readers blocked
the migration's writer. The pragmas installed below mirror the contention half
of `bangla_gpt_api.db.session` (session.py:58-90) narrowly -- the same
timeout, WAL and synchronous=NORMAL, without importing the app's engine
factory or its settings.

`PRAGMA foreign_keys` is deliberately NOT enabled, and this is a considered
decision, not an omission:

* `alembic/versions/c4d8e0f2a6b9_fk_delete_policy.py` rebuilds every SQLite
  table and REQUIRES enforcement to be off -- it raises rather than proceed
  when the pragma is ON (c4d8e0f2a6b9:244-250; rationale at :50-55: a DROP
  TABLE under enforcement would either fail on the dependent rows or fire
  their ON DELETE actions). Enabling the pragma here would abort every upgrade
  from a database older than that revision, i.e. break the chain.
* Alembic's batch mode has the same assumption: it recreates a table by
  dropping the old one, and its own code notes it "assume[s] SQLite no foreign
  keys" (alembic/operations/batch.py:350). Every SQLite rebuild in this chain
  -- a3c5e7f9b1d3, b5d7e9f1a3c7, dbf1d2e3f4a5 -- runs through batch mode.
* Enabling it only for the runs that cannot touch that revision would make
  fresh databases (chain from base) and existing ones (chain from head) behave
  differently, which is the exact class of divergence the schema-invariants
  re-assert exists to remove.

The integrity gap that leaves is reported, not hidden: on SQLite a migration
that orphans rows still passes locally and aborts on PostgreSQL. Closing it
needs the FK-rebuild revision to change its approach (or its guard to run
per-table), which is outside this change's file scope.
"""

from logging.config import fileConfig
from typing import Any

from sqlalchemy import engine_from_config
from sqlalchemy import event
from sqlalchemy import pool
from sqlalchemy.engine import Engine

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the.ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from bangla_gpt_api.config import get_settings
from bangla_gpt_api.db.base import Base
import bangla_gpt_api.db.models  # noqa: F401 ensure tables are registered

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
#... etc.

#: How long a SQLite write waits for the write lock before raising. Mirrors
#: ``bangla_gpt_api.db.session.SQLITE_BUSY_TIMEOUT_MS`` (session.py:44); kept
#: as a local constant so env.py stays importable without the app's settings.
SQLITE_BUSY_TIMEOUT_MS = 15000


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_settings().database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _apply_sqlite_pragmas(connectable: Engine, url: str) -> None:
    """Give the migration connection the runtime contention posture."""
    import sqlite3
    import time

    memory = ":memory:" in url or url.rstrip("/") == "sqlite:"

    @event.listens_for(connectable, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        # The connect listener receives the DBAPI connection untyped, exactly
        # as in db/session.py:63 (SQLAlchemy invokes it after the driver's own
        # connect() returned).
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            if not memory:
                # journal_mode=WAL does not go through the busy handler; read
                # the current mode first (lock-free when already WAL) and only
                # attempt the switch with a bounded retry, exactly like
                # session.py:79-87.
                for _ in range(50):  # <= ~5s
                    mode = cursor.execute("PRAGMA journal_mode").fetchone()
                    if str(mode[0]).lower() == "wal":
                        break
                    try:
                        cursor.execute("PRAGMA journal_mode=WAL")
                        break
                    except sqlite3.OperationalError:
                        time.sleep(0.1)
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = get_settings().database_url
    from sqlalchemy import create_engine

    connectable = create_engine(url)
    if url.startswith("sqlite"):
        _apply_sqlite_pragmas(connectable, url)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
