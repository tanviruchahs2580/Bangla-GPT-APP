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
* ``busy_timeout=5000`` — a contended write waits up to 5s for the lock
  instead of raising ``database is locked`` on the first collision.
* ``journal_mode=WAL`` + ``synchronous=NORMAL`` (file databases only) —
  readers never block the single writer, and WAL + NORMAL is the documented
  safe pairing (a power loss can lose the last transactions, never corrupt
  the database). Skipped for ``:memory:`` where it is meaningless.

``foreign_keys``, ``busy_timeout`` and ``synchronous`` are per-connection
state, so they are applied via a ``connect`` event (``PRAGMA foreign_keys``
is also a no-op inside a transaction, so it must run on the raw connection
before SQLAlchemy starts one). ``journal_mode`` is NOT per-connection state:
it is a database-wide switch that SQLite refuses with an immediate
``SQLITE_BUSY`` while any other connection has a transaction open, ignoring
``busy_timeout`` entirely. Running it on every connection meant that a
sibling gunicorn worker's boot-time ``create_all`` made ``engine.connect()``
fail with "database is locked" (AUD-EF-01, the intermittent docker-smoke
failure), so it is attempted once per engine instead — see ``_enable_wal``.

Postgres session posture (H-04/H-07):

* ``timezone=utc`` — every timestamp column in this schema is a naive
  ``DateTime`` (no ``timezone=True``), while the code stores
  ``datetime.now(UTC)`` values. Naive values are interpreted in the *session*
  timezone, so the stored instant silently shifts on a host or managed
  database whose default is not UTC. Pinning the session to UTC makes the
  stored and returned values unambiguous today; the full ``timestamptz``
  model migration is a larger, separately-owned change with a documented
  plan (docs/operations/TIMEZONE.md).
* ``statement_timeout`` / ``lock_timeout`` — a runaway query or an
  unbounded lock wait is cancelled by the server, so one bad request cannot
  hold one of the ten pooled connections until the client disappears.
* Serialization failures and deadlocks (``40001``/``40P01``) are retried by
  :func:`run_with_retry` — bounded, jittered, and only for transactions the
  server aborted itself.
"""

import logging
import secrets
import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.logging_config import json_log

logger = logging.getLogger(__name__)

#: How long a SQLite write waits for the write lock before raising.
SQLITE_BUSY_TIMEOUT_MS = 5000
#: Bounded retries for the one-off WAL switch when a sibling worker holds the
#: write lock during boot (5 attempts, 0.2s + 0.4s + 0.6s + 0.8s delay).
WAL_SWITCH_ATTEMPTS = 5
WAL_SWITCH_DELAY_SECONDS = 0.2
#: TCP connect budget for PostgreSQL — a hung host fails the connection
#: attempt instead of blocking the (boot-time or request) caller indefinitely.
POSTGRES_CONNECT_TIMEOUT_SECONDS = 10

#: PostgreSQL SQLSTATEs that mean "this transaction lost a race, retry it":
#: 40001 serialization_failure and 40P01 deadlock_detected. Both are safe to
#: retry because the server aborted the whole transaction — no partial write
#: was visible to anyone.
RETRYABLE_SQLSTATES = frozenset({"40001", "40P01"})

T = TypeVar("T")


def postgres_session_options(settings: Settings) -> str:
    """The libpq ``options`` string pinning the Postgres session posture.

    psycopg forwards this verbatim to the server, so the timezone pin and both
    timeouts apply to every pooled connection without an extra round trip.
    Timeout values of 0 are omitted (server default = no timeout).
    """
    parts = ["-c timezone=utc"]
    if settings.db_statement_timeout_ms > 0:
        parts.append(f"-c statement_timeout={int(settings.db_statement_timeout_ms)}")
    if settings.db_lock_timeout_ms > 0:
        parts.append(f"-c lock_timeout={int(settings.db_lock_timeout_ms)}")
    return " ".join(parts)


def _sqlstate(exc: BaseException) -> str | None:
    """Best-effort SQLSTATE for a DBAPI or SQLAlchemy exception."""
    candidates = [exc]
    orig = getattr(exc, "orig", None)
    if orig is not None:
        candidates.append(orig)
    for candidate in candidates:
        for attr in ("sqlstate", "pgcode"):
            value = getattr(candidate, attr, None)
            if isinstance(value, str) and value:
                return value
        diag = getattr(candidate, "diag", None)
        value = getattr(diag, "sqlstate", None) if diag is not None else None
        if isinstance(value, str) and value:
            return value
    return None


def is_retryable_db_error(exc: BaseException) -> bool:
    """True when ``exc`` is a serialization failure or a deadlock (40001/40P01).

    Only these classes are retried: the server aborted the transaction, so
    replaying it cannot double-apply a write.
    """
    return _sqlstate(exc) in RETRYABLE_SQLSTATES


def run_with_retry(
    operation: Callable[[Session], T],
    *,
    session_factory: sessionmaker[Session],
    attempts: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``operation(session)``, retrying serialization failures/deadlocks.

    A fresh session per attempt (an aborted session must not be reused), and
    exponential backoff with full jitter bounded by ``max_delay``. Anything
    that is not 40001/40P01 propagates on the first raising attempt, so a real
    defect is never hidden behind three tries.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    for attempt in range(1, attempts + 1):
        session = session_factory()
        try:
            result = operation(session)
            session.commit()
            return result
        except DBAPIError as exc:
            session.rollback()
            if not is_retryable_db_error(exc) or attempt == attempts:
                raise
            sleep(
                min(max_delay, base_delay * (2 ** (attempt - 1))) * secrets.randbelow(1000) / 1000
            )
        finally:
            session.close()
    raise AssertionError("unreachable")  # pragma: no cover - loop returns or raises


def _is_memory_sqlite(url: str) -> bool:
    return ":memory:" in url or url.rstrip("/") == "sqlite:"


def _apply_sqlite_pragmas(target: Engine, url: str) -> None:
    """Register per-connection pragmas giving SQLite the Postgres contract."""
    memory = _is_memory_sqlite(url)

    @event.listens_for(target, "connect")
    def _set_pragmas(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]  # SQLAlchemy hands the raw DBAPI connection; our listener types it `object`.
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            if not memory:
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def _enable_wal(target: Engine, url: str) -> None:
    """Switch a file database to WAL once, tolerating a concurrent writer.

    This is deliberately NOT in the ``connect`` listener: the statement is a
    database-wide setting whose failure mode (immediate ``SQLITE_BUSY``, busy
    handler not consulted) must never fail a connection attempt. A lost race
    against a sibling worker's boot is retried briefly and then abandoned with
    a warning — WAL is a concurrency optimisation, while write safety comes
    from the per-connection ``busy_timeout`` — and the next engine (or the next
    boot) flips the file, since the mode is persisted in the database header.
    """
    if _is_memory_sqlite(url):
        return
    for attempt in range(1, WAL_SWITCH_ATTEMPTS + 1):
        try:
            with target.connect() as conn:
                mode = conn.exec_driver_sql("PRAGMA journal_mode=WAL").scalar()
            if str(mode).lower() != "wal":
                json_log(logger, logging.WARNING, "sqlite_wal_not_enabled", mode=str(mode))
            return
        except OperationalError as exc:
            locked = "locked" in str(exc).lower()
            if not locked or attempt == WAL_SWITCH_ATTEMPTS:
                json_log(
                    logger,
                    logging.WARNING,
                    "sqlite_wal_switch_skipped",
                    attempt=attempt,
                    error=str(exc)[:200],
                )
                return
            time.sleep(WAL_SWITCH_DELAY_SECONDS * attempt)


def make_engine(settings: Settings) -> Engine:
    url = settings.database_url
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if _is_memory_sqlite(url):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)
        _apply_sqlite_pragmas(engine, url)
        _enable_wal(engine, url)
        return engine
    if url.startswith("postgresql"):
        # Production Postgres: pre-ping + modest pool for 2-4 workers
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
        kwargs["pool_recycle"] = 3600
        kwargs["connect_args"] = {
            "connect_timeout": POSTGRES_CONNECT_TIMEOUT_SECONDS,
            # UTC pin + statement/lock timeouts on every session (H-04/H-07).
            "options": postgres_session_options(settings),
        }
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    # Import the model module for its registration side effect BEFORE
    # create_all: a caller that imported only ``db.session`` leaves
    # Base.metadata empty and this call then creates nothing, silently -- a
    # footgun met while writing the two-process scheduled-job test (the child
    # interpreter imported session but not models and created an empty DB).
    from bangla_gpt_api.db import models  # noqa: F401

    Base.metadata.create_all(engine)
