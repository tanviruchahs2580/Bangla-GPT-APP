"""Engine construction and connection posture.

Cross-engine integrity note: PostgreSQL enforces foreign keys and has a
connection pool with pre-ping; SQLite by default enforces **nothing** —
modern connections default ``foreign_keys=OFF``, ``busy_timeout=0`` (an
immediate ``SQLITE_BUSY`` on the first write contention, no waiting) and
``journal_mode=delete`` (readers block the writer). The same application code
therefore had different data-integrity guarantees per engine, and the live
single-file deployment ran with the weakest one. The pragmas below give the
SQLite engine the same contract the app assumes on Postgres:

* ``foreign_keys=ON`` — declarative FK constraints are enforced, so a delete
  path that misses a child row fails loudly instead of leaving orphans
  (tests run this posture too, by construction).
* ``busy_timeout=SQLITE_BUSY_TIMEOUT_MS`` (15 s, see the constant below) — a
  contended write waits for the lock instead of raising ``database is
  locked`` on the first collision.
* ``journal_mode=WAL`` + ``synchronous=NORMAL`` (file databases only) —
  readers never block the single writer, and WAL + NORMAL is the documented
  safe pairing (a power loss can lose the last transactions, never corrupt
  the database). Skipped for ``:memory:`` where it is meaningless.

Applied per connection via a ``connect`` event, because SQLite resets
per-connection state (and ``PRAGMA foreign_keys`` is a no-op inside a
transaction, so it must run on the raw connection before SQLAlchemy starts
one).
"""

import sqlite3
import time

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.base import Base

#: How long a SQLite write waits for the write lock before raising.
# 15s: the coverage CI leg and single-file production deployments both
# hit multi-second write contention under load; 5s measured "database is
# locked" flakes (CI 2026-10-24, two suites) where 15s absorbed them.
SQLITE_BUSY_TIMEOUT_MS = 15000
#: TCP connect budget for PostgreSQL — a hung host fails the connection
#: attempt instead of blocking the (boot-time or request) caller indefinitely.
POSTGRES_CONNECT_TIMEOUT_SECONDS = 10


def _is_memory_sqlite(url: str) -> bool:
    return ":memory:" in url or url.rstrip("/") == "sqlite:"


def _apply_sqlite_pragmas(target: Engine, url: str) -> None:
    """Register per-connection pragmas giving SQLite the Postgres contract."""
    memory = _is_memory_sqlite(url)

    @event.listens_for(target, "connect")
    def _set_pragmas(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            if not memory:
                # journal_mode=WAL requires exclusive access and does NOT go
                # through the busy handler: two gunicorn workers booting
                # simultaneously against one file (WEB_CONCURRENCY=2, the
                # shipped default) raced here — the losing worker failed to
                # boot, gunicorn's master gave up, and the container exited
                # ~17s after start (reproduced deterministically, 2026-10-24).
                # Read the current mode first (cheap, lock-free in WAL) and
                # only attempt the switch with a bounded retry loop.
                for _ in range(50):  # <= ~5s, like the busy timeout
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


def make_engine(settings: Settings) -> Engine:
    url = settings.database_url
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if _is_memory_sqlite(url):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)
        _apply_sqlite_pragmas(engine, url)
        return engine
    if url.startswith("postgresql"):
        # Production Postgres: pre-ping + modest pool for 2-4 workers
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
        kwargs["pool_recycle"] = 3600
        kwargs["connect_args"] = {"connect_timeout": POSTGRES_CONNECT_TIMEOUT_SECONDS}
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
