"""H-14 / AUD-HI-02: UTC storage, the injectable clock seam, midnight boundaries.

Three properties, each with a test that would fail if the property regressed:

1. **UTC storage** -- ``db/types.UtcDateTime`` writes a ``timestamptz`` on
   PostgreSQL (the instant is unambiguous to any reader) and returns naive UTC
   to Python, which is the contract the ~30 existing ``.replace(tzinfo=None)``
   call sites rely on. The PostgreSQL half runs only when ``TEST_DATABASE_URL``
   is set (the CI postgres job does).
2. **Injectable clock** -- ``db/clock.py`` is the seam; retention reads the time
   through it, so a test can freeze "now" instead of patching :mod:`datetime`
   globally.
3. **Midnight boundaries** -- the Asia/Dhaka day boundary (UTC+6, no DST), the
   Sunday-22:00 digest hour and the retention cutoff are exercised exactly on
   the tick they flip.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.clock import FrozenClock, SystemClock, reset_clock, set_clock, utcnow
from bangla_gpt_api.db.models import EmailVerification, PasswordReset, User
from bangla_gpt_api.db.session import init_db, make_engine, make_session_factory
from bangla_gpt_api.services import retention
from bangla_gpt_api.services.activity import DHAKA, dhaka_date
from bangla_gpt_api.services.parent_digest import digest_due

PG_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
SECRET = "test-secret-0123456789abcdef0123456789"


def _settings(db_path: Path, *, database_url: str | None = None) -> Settings:
    return Settings(
        env="test",
        database_url=database_url or f"sqlite:///{db_path}",
        jwt_secret=SECRET,
        chat_retention_days=30,
    )


def _make_user(db, email: str) -> User:
    user = User(email=email, password_hash="x", role="student")
    db.add(user)
    db.flush()
    return user


@pytest.fixture(autouse=True)
def _restore_clock():
    yield
    reset_clock()


# ── 1. UtcDateTime storage semantics ──────────────────────────────────


def test_utc_datetime_binds_aware_and_reads_back_naive_utc(tmp_path) -> None:
    engine = make_engine(_settings(tmp_path / "utc.db"))
    init_db(engine)
    factory = make_session_factory(engine)
    aware = datetime(2026, 3, 31, 18, 30, tzinfo=UTC)  # 00:30 Dhaka on 1 April
    naive_utc = datetime(2026, 3, 31, 18, 30)
    with factory() as db:
        db.add(User(email="utc@example.com", password_hash="x", role="student", created_at=aware))
        db.commit()
        # A naive value is *defined* to be UTC by the house contract.
        db.add(
            User(email="naive@example.com", password_hash="x", role="student", created_at=naive_utc)
        )
        db.commit()
        loaded = db.query(User).filter_by(email="utc@example.com").one()
        assert loaded.created_at == naive_utc
        assert loaded.created_at.tzinfo is None
        assert db.query(User).filter_by(email="naive@example.com").one().created_at == naive_utc


@pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set (Postgres CI job only)")
def test_postgres_columns_are_timestamptz_and_compare_natively() -> None:
    """The point of the migration: the *database* knows the instant."""
    engine = make_engine(_settings(Path("unused"), database_url=PG_URL))
    inspector = inspect(engine)
    for table, column in (
        ("users", "created_at"),
        ("users", "locked_until"),
        ("quiz_attempts", "created_at"),
        ("email_bounces", "last_bounced_at"),
    ):
        col = next(c for c in inspector.get_columns(table) if c["name"] == column)
        assert str(col["type"]).upper().startswith("TIMESTAMP"), (table, column, col["type"])
        assert getattr(col["type"], "timezone", False) is True, (table, column, col["type"])

    factory = make_session_factory(engine)
    with factory() as db:
        db.execute(text("DELETE FROM users WHERE email = 'h2-pg-utc@example.com'"))
        db.add(
            User(
                email="h2-pg-utc@example.com",
                password_hash="x",
                role="student",
                created_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        db.commit()
        # A naive column could not be compared to now() without an implicit
        # cast that assumes the session timezone; timestamptz can.
        recent = db.execute(
            text(
                "SELECT count(*) FROM users WHERE email = 'h2-pg-utc@example.com'"
                " AND created_at > now() - interval '1 hour'"
            )
        ).scalar_one()
        assert recent == 1
        db.execute(text("DELETE FROM users WHERE email = 'h2-pg-utc@example.com'"))
        db.commit()


# ── 2. the clock seam ─────────────────────────────────────────────────


def test_clock_seam_is_swappable() -> None:
    frozen = FrozenClock(datetime(2026, 6, 1, 23, 59, 59))
    set_clock(frozen)
    assert utcnow() == datetime(2026, 6, 1, 23, 59, 59)
    assert utcnow().tzinfo is None
    frozen.advance(seconds=1)
    assert utcnow() == datetime(2026, 6, 2, 0, 0, 0)
    reset_clock()
    assert isinstance(SystemClock(), SystemClock)
    assert utcnow() - datetime.now(UTC).replace(tzinfo=None) < timedelta(seconds=5)


def test_retention_uses_the_clock_seam_not_the_wall_clock(tmp_path) -> None:
    """A row 31 days past expiry is swept only because the frozen clock says so.

    The frozen instant is 100 days in the FUTURE of the real clock: by wall
    time the row would still be inside the 30-day grace window, so a sweep
    that ignored the seam would delete nothing.
    """
    db_path = tmp_path / "clock.db"
    settings = _settings(db_path)
    engine = make_engine(settings)
    init_db(engine)
    factory = make_session_factory(engine)
    real_now = datetime.now(UTC).replace(tzinfo=None)
    frozen = FrozenClock(real_now + timedelta(days=100))
    set_clock(frozen)
    with factory() as db:
        user = _make_user(db, "seam@example.com")
        db.add(
            PasswordReset(
                user_id=user.id,
                token_hash="a" * 64,
                expires_at=real_now + timedelta(days=31),
            )
        )
        db.commit()
        report = retention.run_retention_sweep(db, settings=settings)
        assert report["password_resets_deleted"] == 1
        assert db.query(PasswordReset).count() == 0


def test_retention_cutoff_is_strict_one_tick_past_the_boundary(tmp_path) -> None:
    """Row exactly ON the cutoff survives; one microsecond older does not."""
    db_path = tmp_path / "boundary.db"
    settings = _settings(db_path)
    engine = make_engine(settings)
    init_db(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 5, 10, 12, 0, 0)
    cutoff = now - timedelta(days=30)  # expiry + TOKEN_GRACE_DAYS == cutoff
    with factory() as db:
        user = _make_user(db, "cutoff@example.com")
        db.add(PasswordReset(user_id=user.id, token_hash="b" * 64, expires_at=cutoff))
        db.add(
            PasswordReset(
                user_id=user.id, token_hash="c" * 64, expires_at=cutoff - timedelta(microseconds=1)
            )
        )
        db.commit()
        report = retention.run_retention_sweep(db, settings=settings, now=now)
        assert report["password_resets_deleted"] == 1
        assert [r.token_hash for r in db.query(PasswordReset).all()] == ["b" * 64]
        # One tick later the boundary row is old enough by the same rule.
        report = retention.run_retention_sweep(
            db, settings=settings, now=now + timedelta(microseconds=1)
        )
        assert report["password_resets_deleted"] == 1
        assert db.query(PasswordReset).count() == 0


# ── 3. midnight boundaries ────────────────────────────────────────────


def test_dhaka_day_boundary_is_exact() -> None:
    # 18:00 UTC = 00:00 Asia/Dhaka (UTC+6, no DST): the day flips exactly here.
    assert dhaka_date(datetime(2026, 1, 31, 17, 59, 59, tzinfo=UTC)) == "2026-01-31"
    assert dhaka_date(datetime(2026, 1, 31, 18, 0, 0, tzinfo=UTC)) == "2026-02-01"
    # Across the leap-day boundary too.
    assert dhaka_date(datetime(2028, 2, 28, 18, 0, 0, tzinfo=UTC)) == "2028-02-29"
    assert dhaka_date(datetime(2028, 2, 29, 18, 0, 0, tzinfo=UTC)) == "2028-03-01"


def test_digest_hour_boundary_is_exact_in_dhaka() -> None:
    """22:00 Dhaka == 16:00 UTC; the digest fires on the exact second."""
    sunday_2200_dhaka = datetime(2026, 9, 6, 16, 0, 0)  # naive UTC
    assert sunday_2200_dhaka.replace(tzinfo=UTC).astimezone(DHAKA).hour == 22
    assert digest_due(sunday_2200_dhaka - timedelta(seconds=1), "")[0] is False
    due, key = digest_due(sunday_2200_dhaka, "")
    assert due and key == "2026-W36"
    # One second into the slot is not a second run (the caller passes its key).
    assert digest_due(sunday_2200_dhaka + timedelta(seconds=1), key)[0] is False


def test_write_across_dhaka_midnight_keeps_the_instant(tmp_path) -> None:
    """A row written at 00:00:01 Dhaka keeps its instant, not its local day."""
    db_path = tmp_path / "midnight.db"
    engine = make_engine(_settings(db_path))
    init_db(engine)
    factory = make_session_factory(engine)
    instant = datetime(2026, 3, 31, 18, 0, 1, tzinfo=UTC)  # 00:00:01 Dhaka, 1 April
    with factory() as db:
        user = _make_user(db, "midnight@example.com")
        db.add(
            EmailVerification(
                user_id=user.id, token_hash="d" * 64, expires_at=instant, created_at=instant
            )
        )
        db.commit()
    conn = sqlite3.connect(db_path)
    try:
        stored = conn.execute(
            "SELECT created_at FROM email_verifications WHERE token_hash = ?", ("d" * 64,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert stored.startswith("2026-03-31 18:00:01"), stored
    # SQLite stores the UTC wall clock; the Dhaka date is a presentation concern.
    parsed = datetime.fromisoformat(stored).replace(tzinfo=UTC)
    assert parsed.astimezone(DHAKA).strftime("%Y-%m-%d") == "2026-04-01"
