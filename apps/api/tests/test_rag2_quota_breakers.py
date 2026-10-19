"""AUD-A2-10 / A7-05: the quota set is complete and each control is honest.

Present before: per-user rate limits, a 1000-char input cap, a 2048-token
output cap and an opt-in per-user monthly budget. Added here and pinned by
these tests:

* a whole-deployment DAILY cost breaker (an abuse loop spreads across
  accounts, so a per-account cap is not enough);
* a per-SCHOOL daily cost breaker (one school cannot consume the platform);
* a conversation-length cap (an unbounded conversation is an unbounded bill);
* an in-flight (concurrency) cap for one identity, on the shared backend;
* every control is 0 = disabled by default, so enabling one is an explicit
  operational decision, and a disabled control is a no-op (proven, not
  assumed).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models import AiUsage, ChatMessage, Conversation, School, Student, User
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.ratelimit import (
    ConcurrencyLimitExceeded,
    MemoryConcurrencyLimiter,
    RedisConcurrencyLimiter,
    build_concurrency_limiter,
    concurrency_slot,
)
from bangla_gpt_api.services.costs import (
    check_conversation_cap,
    check_daily_cost_breaker,
    check_school_daily_budget,
    day_cost_usd,
    school_day_cost_usd,
)

SECRET = "test-secret-0123456789abcdef0123456789"


def _session(tmp_path) -> Session:
    settings = _settings(database_url=f"sqlite:///{tmp_path}/quota.db")
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _settings(**over) -> Settings:
    return Settings(env="test", jwt_secret=SECRET, **over)


def _user(db: Session, email: str, *, school_id: int | None = None) -> User:
    user = User(
        email=email,
        password_hash="x",
        role="student",
        school_id=school_id,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    return user


def _usage(db: Session, user: User, cost: float, *, when: datetime | None = None) -> None:
    row = AiUsage(
        user_id=user.id,
        route="tutor.ask",
        model="mock",
        prompt_tokens=1,
        completion_tokens=1,
        estimated_cost_usd=cost,
    )
    if when is not None:
        row.created_at = when
    db.add(row)
    db.commit()


# ---------------------------------------------------------- daily breaker ---
def test_daily_breaker_is_disabled_by_default(tmp_path) -> None:
    db = _session(tmp_path)
    user = _user(db, "d1@test.local")
    _usage(db, user, 999.0)
    check_daily_cost_breaker(db, settings=_settings())  # no raise


def test_daily_breaker_blocks_when_the_ceiling_is_reached(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _session(tmp_path)
    user = _user(db, "d2@test.local")
    _usage(db, user, 3.0)
    check_daily_cost_breaker(db, settings=_settings())  # default 0 = off
    # The switch is the documented env fallback until the Settings field
    # lands (handoff api-rag2.md); a settings object field takes precedence.
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "2.5")
    with pytest.raises(HTTPException) as excinfo:
        check_daily_cost_breaker(db, settings=_settings())
    assert excinfo.value.status_code == 429
    assert excinfo.value.detail["code"] == "ai_daily_budget_exceeded"

    class _Budgeted:
        ai_daily_budget_usd = 2.5

    with pytest.raises(HTTPException):
        check_daily_cost_breaker(db, settings=_Budgeted())
    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "not-a-number")
    check_daily_cost_breaker(db, settings=_settings())  # malformed -> default off


def test_day_cost_only_counts_today(tmp_path) -> None:
    db = _session(tmp_path)
    user = _user(db, "d3@test.local")
    yesterday = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    _usage(db, user, 5.0, when=yesterday)
    _usage(db, user, 1.25, when=datetime.now(UTC).replace(tzinfo=None))
    assert day_cost_usd(db) == pytest.approx(1.25, abs=1e-9)
    assert day_cost_usd(db, user_id=user.id) == pytest.approx(1.25, abs=1e-9)


# --------------------------------------------------------- school breaker ---
def test_school_breaker_counts_only_that_school(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session(tmp_path)
    school = School(name="S1", code="S1")
    other = School(name="S2", code="S2")
    db.add_all([school, other])
    db.commit()
    alice = _user(db, "sa@test.local", school_id=school.id)
    bob = _user(db, "sb@test.local", school_id=other.id)
    _usage(db, alice, 2.0)
    _usage(db, bob, 0.1)
    assert school_day_cost_usd(db, school_id=school.id) == pytest.approx(2.0, abs=1e-9)
    monkeypatch.setenv("AI_DAILY_BUDGET_USD_PER_SCHOOL", "1.0")
    with pytest.raises(HTTPException) as excinfo:
        check_school_daily_budget(db, school_id=school.id, settings=_settings())
    assert excinfo.value.detail["code"] == "ai_school_budget_exceeded"
    # the other school is unaffected
    check_school_daily_budget(db, school_id=other.id, settings=_settings())


def test_school_breaker_noops_for_users_without_a_school_and_when_disabled(tmp_path) -> None:
    db = _session(tmp_path)
    alice = _user(db, "sa2@test.local")
    _usage(db, alice, 9.0)
    check_school_daily_budget(db, school_id=None, settings=_settings())  # no school -> no-op
    check_school_daily_budget(db, school_id=1, settings=_settings())  # disabled -> no-op


# ------------------------------------------------------ conversation cap ----
def _conversation(db: Session, user: User, messages: int) -> Conversation:
    student = db.query(Student).filter(Student.user_id == user.id).one_or_none()
    if student is None:
        student = Student(user_id=user.id, name="শিক্ষার্থী", class_level=6)
        db.add(student)
        db.commit()
    conv = Conversation(student_id=student.id, title="t")
    db.add(conv)
    db.commit()
    for _ in range(messages):
        db.add(ChatMessage(conversation_id=conv.id, role="user", content="কোষ কী?"))
    db.commit()
    return conv


def test_conversation_cap_blocks_the_next_turn(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session(tmp_path)
    user = _user(db, "c1@test.local")
    conv = _conversation(db, user, 4)
    # default 200: a 4-message conversation is fine
    check_conversation_cap(db, conversation_id=conv.id, settings=_settings())
    check_conversation_cap(db, conversation_id=conv.id, settings=_settings(), extra_messages=1)
    monkeypatch.setenv("AI_MAX_CONVERSATION_MESSAGES", "4")
    with pytest.raises(HTTPException) as excinfo:
        check_conversation_cap(db, conversation_id=conv.id, settings=_settings())
    assert excinfo.value.status_code == 429
    assert excinfo.value.detail["code"] == "conversation_limit_reached"


def test_conversation_cap_zero_disables_it_and_other_conversations_are_free(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _session(tmp_path)
    user = _user(db, "c2@test.local")
    conv = _conversation(db, user, 3)
    other = _conversation(db, user, 0)
    monkeypatch.setenv("AI_MAX_CONVERSATION_MESSAGES", "0")
    check_conversation_cap(db, conversation_id=conv.id, settings=_settings())
    monkeypatch.setenv("AI_MAX_CONVERSATION_MESSAGES", "1")
    check_conversation_cap(db, conversation_id=other.id, settings=_settings())


# ---------------------------------------------------------- concurrency ----
def test_memory_concurrency_limiter_counts_in_flight_slots() -> None:
    limiter = MemoryConcurrencyLimiter()
    assert limiter.acquire("u1", 2) is True
    assert limiter.acquire("u1", 2) is True
    assert limiter.acquire("u1", 2) is False  # cap reached
    assert limiter.acquire("u2", 2) is True  # other identity unaffected
    limiter.release("u1")
    assert limiter.acquire("u1", 2) is True
    limiter.release("u1")
    limiter.release("u1")
    limiter.release("u1")  # idempotent
    assert limiter.acquire("u1", 2) is True


def test_memory_concurrency_slots_expire_after_the_safety_ttl() -> None:
    import time

    limiter = MemoryConcurrencyLimiter(slot_ttl=0.05)
    assert limiter.acquire("u1", 1) is True
    assert limiter.acquire("u1", 1) is False
    time.sleep(0.06)
    # the slot expired: a worker that died mid-turn cannot leak it forever
    assert limiter.acquire("u1", 1) is True


def test_concurrency_slot_context_manager_releases_on_error() -> None:
    limiter = MemoryConcurrencyLimiter()
    with pytest.raises(RuntimeError):
        with concurrency_slot(limiter, "u1", 1):
            raise RuntimeError("boom")
    with concurrency_slot(limiter, "u1", 1):
        pass  # the slot is free again


def test_concurrency_slot_refuses_past_the_cap() -> None:
    limiter = MemoryConcurrencyLimiter()
    with concurrency_slot(limiter, "u1", 1):
        with pytest.raises(ConcurrencyLimitExceeded):
            with concurrency_slot(limiter, "u1", 1):
                pass


def test_concurrency_slot_with_limit_zero_is_a_noop() -> None:
    limiter = MemoryConcurrencyLimiter()
    with concurrency_slot(limiter, "u1", 0):
        pass


class _FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    def incr(self, name: str) -> int:
        self.counters[name] = self.counters.get(name, 0) + 1
        return self.counters[name]

    def decr(self, name: str) -> int:
        self.counters[name] = self.counters.get(name, 0) - 1
        return self.counters[name]

    def expire(self, name: str, seconds: int) -> bool:
        self.expiries[name] = seconds
        return True

    def delete(self, name: str) -> int:
        self.counters.pop(name, None)
        return 1


def test_redis_concurrency_limiter_is_shared_and_never_leaks_a_slot() -> None:
    limiter = RedisConcurrencyLimiter.__new__(RedisConcurrencyLimiter)
    fake = _FakeRedis()
    limiter._fail_open = False
    limiter._redis = fake
    assert limiter.acquire("u1", 2) is True
    assert limiter.acquire("u1", 2) is True
    assert limiter.acquire("u1", 2) is False  # refused, slot handed straight back
    assert fake.counters["cc:u1"] == 2
    limiter.release("u1")
    limiter.release("u1")
    assert "cc:u1" not in fake.counters  # counter deleted at zero
    assert fake.expiries["cc:u1"] > 0  # every take refreshes the safety TTL


def test_build_concurrency_limiter_matches_the_rate_limit_backend(tmp_path) -> None:
    assert isinstance(build_concurrency_limiter(_settings()), MemoryConcurrencyLimiter)
    with pytest.raises(ValueError):
        build_concurrency_limiter(_settings(rate_limit_backend="redis", redis_url=None))
