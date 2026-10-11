"""Single-use artefacts must be redeemed exactly once, even under concurrency.

AUD-0034: verification codes, reset tokens and invite codes were redeemed
with a SELECT ... WHERE used_at IS NULL followed by ``row.used_at = now``.
That is check-then-act.

Measured, not assumed. Two implementations were raced against two
concurrent clients, 40 iterations each:

    engine        implementation            result
    ------------  ------------------------  -------------------------
    SQLite WAL    check-then-act (old)      double-redeemed  0/40
    SQLite WAL    conditional UPDATE (fix)  wrong winner     0/40
    PostgreSQL16  check-then-act (old)      double-redeemed 40/40
    PostgreSQL16  conditional UPDATE (fix)  wrong winner     0/40

So the defect is real and it is the *normal* outcome on Postgres, which is
the production engine -- but SQLite serialises writers tightly enough to hide
it completely. A SQLite-only suite can never detect this, which is why the
deterministic tests below run everywhere and the true race tests require
TEST_DATABASE_URL (the `postgres` CI job sets it).

The fix is a single conditional UPDATE so the database performs the
compare-and-set.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from bangla_gpt_api.auth.security import hash_password
from bangla_gpt_api.auth.single_use import claim_single_use, fetch_by_hash
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models import EmailVerification, PasswordReset, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
requires_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "SQLite serialises writers and cannot demonstrate this race: measured "
        "0/40 double-redemptions on SQLite vs 40/40 on PostgreSQL 16. This "
        "test only means something on the production engine."
    ),
)


@pytest.fixture
def file_db(tmp_path):
    """A real database two connections can contend on.

    Uses PostgreSQL when TEST_DATABASE_URL is set, otherwise a file-backed
    SQLite database so the deterministic tests still run everywhere.
    """
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    else:
        engine = create_engine(
            f"sqlite:///{(tmp_path / 'race.db').as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )

        @event.listens_for(engine, "connect")
        def _wal(dbapi_conn, _rec):  # pragma: no cover - driver setup
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.close()

    if not TEST_DATABASE_URL:
        Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _seed(session: Session) -> tuple[User, str]:
    # Unique per call: against a persistent PostgreSQL database the rows
    # survive between tests, so a fixed email would collide on ix_users_email.
    user = User(
        email=f"racer-{uuid4().hex[:12]}@example.test",
        password_hash=hash_password("Str0ngPassw0rd!"),
        role="student",
    )
    session.add(user)
    session.commit()
    return user, uuid4().hex + uuid4().hex


def _add_verification(session: Session, user_id: int, token_hash: str) -> None:
    session.add(
        EmailVerification(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30),
        )
    )
    session.commit()


# --- sequential contract -----------------------------------------------------


def test_second_claim_of_the_same_code_fails(file_db):
    with Session(file_db) as s:
        user, token_hash = _seed(s)
        _add_verification(s, user.id, token_hash)
        now = datetime.now(UTC).replace(tzinfo=None)

        assert (
            claim_single_use(
                s,
                EmailVerification,
                hash_column=EmailVerification.token_hash,
                hash_value=token_hash,
                now=now,
            )
            is True
        )
        s.commit()

        # Second attempt, same code, fresh session: must lose.
        with Session(file_db) as s2:
            assert (
                claim_single_use(
                    s2,
                    EmailVerification,
                    hash_column=EmailVerification.token_hash,
                    hash_value=token_hash,
                    now=now,
                )
                is False
            )


def test_expired_code_cannot_be_claimed(file_db):
    with Session(file_db) as s:
        user, token_hash = _seed(s)
        s.add(
            EmailVerification(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
            )
        )
        s.commit()
        assert (
            claim_single_use(
                s,
                EmailVerification,
                hash_column=EmailVerification.token_hash,
                hash_value=token_hash,
                now=datetime.now(UTC).replace(tzinfo=None),
            )
            is False
        )


def test_unknown_hash_cannot_be_claimed(file_db):
    with Session(file_db) as s:
        now = datetime.now(UTC).replace(tzinfo=None)
        assert (
            claim_single_use(
                s,
                PasswordReset,
                hash_column=PasswordReset.token_hash,
                hash_value="f" * 64,
                now=now,
            )
            is False
        )


def test_fetch_by_hash_sees_the_stamp(file_db):
    with Session(file_db) as s:
        user, token_hash = _seed(s)
        _add_verification(s, user.id, token_hash)
        now = datetime.now(UTC).replace(tzinfo=None)
        assert (
            claim_single_use(
                s,
                EmailVerification,
                hash_column=EmailVerification.token_hash,
                hash_value=token_hash,
                now=now,
            )
            is True
        )
        row = fetch_by_hash(
            s,
            EmailVerification,
            hash_column=EmailVerification.token_hash,
            hash_value=token_hash,
        )
        assert row is not None and row.used_at is not None


# --- the actual race ---------------------------------------------------------


@requires_postgres
def test_concurrent_claims_of_one_token_produce_exactly_one_winner(file_db):
    """Two threads, two sessions, one token: exactly one may claim it.

    Measured 40/40 double-redemption with the old check-then-act code on
    PostgreSQL 16, so this test fails loudly if the atomic UPDATE is reverted.
    """
    with Session(file_db) as s:
        user, token_hash = _seed(s)
        _add_verification(s, user.id, token_hash)

    now = datetime.now(UTC).replace(tzinfo=None)
    factory = sessionmaker(bind=file_db, autoflush=False, expire_on_commit=False)
    start = threading.Barrier(2)
    results: list[bool] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def attempt() -> None:
        session = factory()
        try:
            start.wait(timeout=10)
            won = claim_single_use(
                session,
                EmailVerification,
                hash_column=EmailVerification.token_hash,
                hash_value=token_hash,
                now=now,
            )
            session.commit()
            with lock:
                results.append(won)
        except OperationalError as exc:  # pragma: no cover - driver dependent
            with lock:
                errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"claim raised {errors}"
    assert len(results) == 2, f"expected 2 results, got {results}"
    assert results.count(True) == 1, f"exactly one winner expected, got {results}"


@requires_postgres
def test_reset_token_is_consumed_once_under_contention(file_db):
    """Same race on the /auth/reset path, which is the credential-critical one."""
    with Session(file_db) as s:
        user, token_hash = _seed(s)
        s.add(
            PasswordReset(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30),
            )
        )
        s.commit()

    now = datetime.now(UTC).replace(tzinfo=None)
    factory = sessionmaker(bind=file_db, autoflush=False, expire_on_commit=False)
    start = threading.Barrier(2)
    results: list[bool] = []

    def attempt() -> None:
        session = factory()
        try:
            start.wait(timeout=10)
            won = claim_single_use(
                session,
                PasswordReset,
                hash_column=PasswordReset.token_hash,
                hash_value=token_hash,
                now=now,
            )
            session.commit()
            results.append(won)
        finally:
            session.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert results.count(True) == 1, f"exactly one winner expected, got {results}"

    # Target this test's token, not the table: against a persistent PostgreSQL
    # database rows from earlier runs are still present.
    with Session(file_db) as s:
        row = s.execute(
            select(PasswordReset).where(PasswordReset.token_hash == token_hash)
        ).scalar_one()
        assert row.used_at is not None
