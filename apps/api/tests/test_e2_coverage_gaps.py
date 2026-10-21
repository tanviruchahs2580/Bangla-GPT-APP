"""E-03: branch-coverage edge cases for the critical-module set.

The audit measured (AUD-EF-03, evidence `E-EF-028`) that the seven modules
carrying authentication, single-use tokens, rate limiting, tenancy, quiz
scoring and retention sat between 50 % and 94 % *branch* coverage while the
overall suite looked healthy at 92 % line — the classic shape of a suite that
tests the happy path of critical code and leaves the failure branches to
production.

These tests target the branches the coverage report showed as *partial or
missing*, and they assert what the branch is for:

* `auth/single_use.py` — the waived-expiry and extra-condition paths of the
  compare-and-set claim, and the read-after-claim returning None;
* `security.py` — every branch of the Fernet PII round-trip (no key, prefix-less
  legacy value, wrong key) and the audit-row defaults;
* `ratelimit.py` — memory-limiter key-space eviction, the concurrency limiter
  (slots, TTL sweep, release) and both Redis concurrency paths, including the
  over-cap give-back and the fail-open/fail-closed splits;
* `services/quiz.py` — generator fallbacks (no candidate, no distractors,
  morphological twins, missing distractor pool) and the second-pass harvest;
* `services/retention.py` — the token/invite/analytics sweeps and the
  feedback-detach branch when a conversation has no messages.

Every test names the branch it covers and the mutation that makes it fail; the
before/after numbers are recorded in `E-R2-e2-001` (before) and `E-R2-e2-002`
(after). Bengali text is built from `tests/factories.py` (escapes only).
"""

from __future__ import annotations

import time
from collections import deque
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from bangla_gpt_api.auth.single_use import claim_single_use, fetch_by_hash
from bangla_gpt_api.db.base import Base
from bangla_gpt_api.db.models import (
    AnalyticsEventRow,
    ChatMessage,
    Conversation,
    EmailVerification,
    ParentInvite,
    PasswordReset,
    Student,
    StudentInvite,
)
from bangla_gpt_api.ratelimit import (
    ConcurrencyLimitExceeded,
    MemoryConcurrencyLimiter,
    MemoryRateLimiter,
    RateLimitBackendError,
    RedisConcurrencyLimiter,
    build_concurrency_limiter,
    build_limiter,
    concurrency_slot,
)
from bangla_gpt_api.security import decrypt_pii, encrypt_pii, write_audit
from bangla_gpt_api.services import retention
from bangla_gpt_api.services.quiz import ClozeQuizGenerator, dump_quiz
from factories import BN, BN_SENTENCE, make_student, make_user, utcnow

# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/gaps.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


class FakeRedis:
    """Minimal sync Redis surface used by the two Redis limiters."""

    def __init__(self, *, fail: bool = False) -> None:
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.deleted: list[str] = []
        self.fail = fail

    def _guard(self) -> None:
        if self.fail:
            import redis.exceptions

            raise redis.exceptions.ConnectionError("backend down")

    def incr(self, name: str) -> int:
        self._guard()
        self.store[name] = self.store.get(name, 0) + 1
        return self.store[name]

    def decr(self, name: str) -> int:
        self._guard()
        self.store[name] = self.store.get(name, 0) - 1
        return self.store[name]

    def expire(self, name: str, ttl: int) -> None:
        self._guard()
        self.ttls[name] = ttl

    def delete(self, name: str) -> None:
        self._guard()
        self.store.pop(name, None)
        self.deleted.append(name)


# ── auth/single_use.py ────────────────────────────────────────────────────


def test_claim_with_expiry_waived_accepts_an_expired_row(db) -> None:
    """``require_unexpired=False`` is the documented waiver; the default refuses.

    Covers the ``if require_unexpired:`` branch both ways on an expired row
    (the only shape the schema allows: ``expires_at`` is NOT NULL, and the
    docstring's NULL case is the same NULL-is-not-true outcome SQL gives).
    Mutation that breaks it: dropping the
    ``conditions.append(model.expires_at >= now)`` line -- the default call
    would then claim an expired code.
    """
    user = make_user(db)
    expired_hash = "a" * 64
    db.add(
        EmailVerification(
            user_id=user.id,
            token_hash=expired_hash,
            expires_at=utcnow() - timedelta(minutes=1),
        )
    )
    db.commit()

    now = utcnow()
    assert (
        claim_single_use(
            db,
            EmailVerification,
            hash_column=EmailVerification.token_hash,
            hash_value=expired_hash,
            now=now,
        )
        is False
    ), "an expired code is refused under the default expiry check"

    assert (
        claim_single_use(
            db,
            EmailVerification,
            hash_column=EmailVerification.token_hash,
            hash_value=expired_hash,
            now=now,
            require_unexpired=False,
        )
        is True
    ), "with the expiry check waived the claim is decided by used_at alone"


def test_claim_on_the_expiry_boundary_second_is_accepted(db) -> None:
    """The cutoff second is inclusive: ``expires_at >= now`` (H-14's question).

    Mutation that breaks it: ``>=`` -> ``>`` in the claim's WHERE clause -- a
    code that expires exactly at the boundary instant would be refused, which
    is the off-by-one the clock seam exists to pin down.
    """
    user = make_user(db)
    boundary_hash = "e" * 64
    moment = utcnow()
    db.add(EmailVerification(user_id=user.id, token_hash=boundary_hash, expires_at=moment))
    db.commit()

    assert (
        claim_single_use(
            db,
            EmailVerification,
            hash_column=EmailVerification.token_hash,
            hash_value=boundary_hash,
            now=moment,
        )
        is True
    )


def test_claim_with_an_extra_condition_still_requires_the_hash_and_expiry(db) -> None:
    """The optional ``extra_condition`` narrows the claim, never widens it.

    Mutation that breaks it: applying ``extra_condition`` with ``or_`` instead
    of an additional ``AND``, or building ``stmt`` before adding it.
    """
    user = make_user(db)
    token_hash = "b" * 64
    other = EmailVerification(
        user_id=user.id, token_hash="c" * 64, expires_at=utcnow() + timedelta(hours=1)
    )
    db.add_all(
        [
            EmailVerification(
                user_id=user.id, token_hash=token_hash, expires_at=utcnow() + timedelta(hours=1)
            ),
            other,
        ]
    )
    db.commit()

    assert (
        claim_single_use(
            db,
            EmailVerification,
            hash_column=EmailVerification.token_hash,
            hash_value=token_hash,
            now=utcnow(),
            extra_condition=EmailVerification.user_id == user.id + 1,
        )
        is False
    ), "a row that fails the extra condition must not be claimed"

    assert (
        claim_single_use(
            db,
            EmailVerification,
            hash_column=EmailVerification.token_hash,
            hash_value=token_hash,
            now=utcnow(),
            extra_condition=EmailVerification.user_id == user.id,
        )
        is True
    )


def test_fetch_by_hash_returns_none_for_an_unknown_hash(db) -> None:
    """The None branch of ``fetch_by_hash`` (callers treat None as rejection).

    Mutation that breaks it: ``.scalar_one()`` instead of
    ``.scalar_one_or_none()`` -- the unknown-hash path raises instead of
    returning None.
    """
    assert (
        fetch_by_hash(
            db,
            PasswordReset,
            hash_column=PasswordReset.token_hash,
            hash_value="d" * 64,
        )
        is None
    )


# ── security.py ───────────────────────────────────────────────────────────


def test_pii_roundtrip_no_key_is_passthrough_and_none_stays_none() -> None:
    """No key configured -> plaintext passthrough (dev/test behaviour)."""
    assert encrypt_pii(None, "key") is None
    assert decrypt_pii(None, "key") is None
    assert encrypt_pii("01712345678", None) == "01712345678"
    assert decrypt_pii("01712345678", None) == "01712345678"


def test_pii_legacy_value_without_prefix_is_returned_unchanged() -> None:
    """Values written before a key existed carry no prefix and are not decrypted.

    Mutation that breaks it: dropping the ``startswith(_FERNET_PREFIX)`` guard
    (the legacy value would be handed to Fernet and raise/return None).
    """
    assert decrypt_pii("plain-guardian-phone", "any-key") == "plain-guardian-phone"


def test_pii_fernet_value_without_a_key_is_unavailable_not_crashing() -> None:
    """A ciphertext with no key configured -> None (documented as unavailable)."""
    key = Fernet.generate_key().decode()
    stored = encrypt_pii("01712345678", key)
    assert stored is not None and stored.startswith("fernet:")
    assert decrypt_pii(stored, None) is None


def test_pii_wrong_key_decrypts_to_none_and_logs() -> None:
    """Key rotation: an old ciphertext decrypts to None instead of raising.

    Mutation that breaks it: removing the ``except InvalidToken`` handler --
    the admin page would 500 during a rotation.
    """
    stale = encrypt_pii("01712345678", Fernet.generate_key().decode())
    fresh_key = Fernet.generate_key().decode()
    assert decrypt_pii(stale, fresh_key) is None


def test_audit_row_defaults_are_recorded_for_an_anonymous_actor(db) -> None:
    """``actor_role=None`` -> 'anonymous' and ``detail=None`` -> {}.

    Mutation that breaks it: storing the raw None (the audit query then breaks
    on a NULL role) or dropping the ``detail or {}`` default.
    """
    write_audit(
        db,
        action="purge",
        actor_user_id=None,
        actor_role=None,
        target=None,
        detail=None,
    )
    db.commit()
    from bangla_gpt_api.db.models import AuditLog

    row = db.execute(select(AuditLog)).scalars().one()
    assert row.actor_role == "anonymous"
    assert row.detail == {}
    assert row.actor_user_id is None and row.target is None


# ── ratelimit.py ──────────────────────────────────────────────────────────


def test_memory_limiter_evicts_stale_keys_when_the_key_space_is_full() -> None:
    """At ``max_keys`` the sweep drops keys whose hits are outside the window.

    Mutation that breaks it: removing the stale sweep (live keys would be
    dropped instead, or the dict would grow past ``max_keys``).
    """
    limiter = MemoryRateLimiter(max_keys=3)
    now = time.monotonic()
    for key, age in (("old-a", 120.0), ("old-b", 90.0), ("old-c", 61.0)):
        limiter._hits[key] = deque([now - age])
    assert limiter.check("fresh", 5) is True
    assert not {"old-a", "old-b", "old-c"} & set(limiter._hits), (
        "every key whose last hit is outside the window is dropped"
    )
    assert len(limiter._hits) <= limiter._max_keys


def test_memory_limiter_forgets_hits_that_left_the_window() -> None:
    """Hits older than 60s are popped from the *checked* key's own deque.

    The window is a sliding one: a student who made 3 requests 61 seconds ago
    must not be limited now. Mutation that breaks it: dropping the
    ``while hits and now - hits[0] >= 60.0: hits.popleft()`` loop -- old hits
    would accumulate and the limiter would lock an identity out permanently.
    """
    limiter = MemoryRateLimiter()
    now = time.monotonic()
    limiter._hits["k"] = deque([now - 120.0, now - 90.0, now - 61.0])
    assert limiter.check("k", 3) is True, "the three stale hits are outside the window"
    assert len(limiter._hits["k"]) == 1, "the stale hits were popped, the new one kept"


def test_memory_limiter_drops_the_least_recently_hit_key_when_none_are_stale() -> None:
    """All keys live and the space is full -> the least recently hit goes.

    Mutation that breaks it: keeping the ``overflow`` slice boundary at
    ``>= max_keys`` (nothing is evicted and the dict grows without bound) or
    evicting the most recently hit key instead.
    """
    limiter = MemoryRateLimiter(max_keys=3)
    now = time.monotonic()
    limiter._hits["a"] = deque([now - 30.0])  # oldest
    limiter._hits["b"] = deque([now - 10.0])
    limiter._hits["c"] = deque([now - 1.0])
    assert limiter.check("d", 5) is True
    assert "a" not in limiter._hits, "the least recently hit key is evicted first"
    assert len(limiter._hits) <= limiter._max_keys


def test_memory_concurrency_limiter_counts_slots_and_frees_them() -> None:
    """Two slots for a limit of two; the third acquisition is refused.

    Mutation that breaks it: ``count >= limit`` -> ``count > limit`` (the cap
    is off by one) or a release that never pops the key at zero.
    """
    limiter = MemoryConcurrencyLimiter()
    assert limiter.acquire("student", 2) is True
    assert limiter.acquire("student", 2) is True
    assert limiter.acquire("student", 2) is False
    limiter.release("student")
    assert limiter.acquire("student", 2) is True
    limiter.release("student")
    limiter.release("student")
    assert limiter._slots == {}, "release drops the key once the count reaches zero"
    limiter.release("never-acquired")  # idempotent: no KeyError


def test_memory_concurrency_limiter_sweeps_expired_slots() -> None:
    """A crashed turn's slot expires after the safety TTL.

    Mutation that breaks it: never comparing ``expires <= now`` in ``_sweep``
    -- a worker that died mid-turn would leak its slot forever.
    """
    limiter = MemoryConcurrencyLimiter(slot_ttl=0.05)
    assert limiter.acquire("student", 1) is True
    assert limiter.acquire("student", 1) is False
    time.sleep(0.2)  # 3x TTL: 0.06 was a host-speed coin flip on Windows
    assert limiter.acquire("student", 1) is True, "the stale slot must be swept"


def test_concurrency_slot_releases_on_success_and_on_exception() -> None:
    """The context manager always gives the slot back.

    Mutation that breaks it: moving ``limiter.release(key)`` out of the
    ``finally`` -- an exception inside the turn leaks a slot permanently.
    """
    limiter = MemoryConcurrencyLimiter()
    with concurrency_slot(limiter, "k", 1):
        assert limiter.acquire("k", 1) is False, "the block holds the only slot"
    assert limiter._slots == {}

    with pytest.raises(ValueError), concurrency_slot(limiter, "k", 1):
        raise ValueError("turn failed")
    assert limiter._slots == {}, "the slot is released even when the turn raises"


def test_concurrency_slot_bypasses_the_limit_when_it_is_disabled() -> None:
    """``limit <= 0`` means "not enforced": no acquisition, no release.

    Mutation that breaks it: removing the early ``yield`` -- a 0 limit would
    refuse every generation instead of disabling the cap.
    """
    limiter = MemoryConcurrencyLimiter()
    with concurrency_slot(limiter, "k", 0):
        pass
    assert limiter._slots == {}, "a disabled cap acquires nothing"


def test_concurrency_slot_raises_when_the_cap_is_reached() -> None:
    limiter = MemoryConcurrencyLimiter()
    limiter.acquire("k", 1)
    with pytest.raises(ConcurrencyLimitExceeded) as exc:
        with concurrency_slot(limiter, "k", 1):
            pass  # pragma: no cover - must not enter
    assert "concurrency limit 1 reached" in str(exc.value)


def test_redis_concurrency_limiter_gives_the_slot_back_over_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over the cap the counter is decremented again (never left held).

    Mutation that breaks it: dropping ``self._redis.decr(name)`` before
    returning False -- every refused request would permanently inflate the
    counter, wedging the identity out of its own quota.
    """
    limiter = RedisConcurrencyLimiter("redis://localhost:6379/0")
    fake = FakeRedis()
    monkeypatch.setattr(limiter, "_redis", fake)

    assert limiter.acquire("s", 1) is True
    assert limiter.acquire("s", 1) is False
    assert fake.store["cc:s"] == 1, "the refused acquisition must give its slot back"
    assert fake.ttls["cc:s"] == 300, "the slot TTL is refreshed on every acquire"


def test_redis_concurrency_limiter_failure_posture_both_ways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreachable Redis: fail closed by default, fail open when configured.

    Mutation that breaks it: inverting the ``_fail_open`` test (the documented
    fail-closed default would become fail-open).
    """
    closed = RedisConcurrencyLimiter("redis://localhost:6379/0")
    monkeypatch.setattr(closed, "_redis", FakeRedis(fail=True))
    with pytest.raises(RateLimitBackendError):
        closed.acquire("s", 1)
    with pytest.raises(RateLimitBackendError):
        closed.release("s")

    opened = RedisConcurrencyLimiter("redis://localhost:6379/0", fail_open=True)
    monkeypatch.setattr(opened, "_redis", FakeRedis(fail=True))
    assert opened.acquire("s", 1) is True
    opened.release("s")  # no raise in fail-open mode


def test_redis_concurrency_release_deletes_the_key_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``release`` deletes the counter once it reaches zero (no key leak).

    Mutation that breaks it: dropping the ``if remaining <= 0`` delete -- the
    key would linger with its TTL and a later acquire would start from a
    stale count.
    """
    limiter = RedisConcurrencyLimiter("redis://localhost:6379/0")
    fake = FakeRedis()
    monkeypatch.setattr(limiter, "_redis", fake)
    limiter.acquire("s", 5)
    limiter.release("s")
    assert fake.deleted == ["cc:s"] and "cc:s" not in fake.store


def test_limiter_factories_validate_their_input(tmp_path) -> None:
    """Both factories refuse a non-Settings object and a redis backend with no URL.

    Mutation that breaks it: dropping the isinstance guard (an AttributeError
    instead of the documented TypeError) or the ``redis_url`` check (a
    confusing redis-py error at request time).
    """
    from bangla_gpt_api.config import Settings

    with pytest.raises(TypeError):
        build_limiter(object())
    with pytest.raises(TypeError):
        build_concurrency_limiter(object())

    redis_no_url = Settings(env="test", rate_limit_backend="redis", redis_url="")
    with pytest.raises(ValueError):
        build_limiter(redis_no_url)
    with pytest.raises(ValueError):
        build_concurrency_limiter(redis_no_url)

    memory = Settings(env="test", rate_limit_backend="memory")
    assert isinstance(build_limiter(memory), MemoryRateLimiter)
    assert isinstance(build_concurrency_limiter(memory), MemoryConcurrencyLimiter)

    # The configured backend branch: a redis URL must select the Redis
    # implementations (constructed lazily -- no connection is opened here).
    from bangla_gpt_api.ratelimit import RedisRateLimiter

    redis_cfg = Settings(
        env="test", rate_limit_backend="redis", redis_url="redis://localhost:6379/0"
    )
    assert isinstance(build_limiter(redis_cfg), RedisRateLimiter)
    assert isinstance(build_concurrency_limiter(redis_cfg), RedisConcurrencyLimiter)


# ── services/quiz.py ──────────────────────────────────────────────────────


def _quiz_corpus():  # local import keeps this file importable without the corpus
    from bangla_gpt_api.data.loader import load_sample_corpus

    return load_sample_corpus()


def test_cloze_questions_carry_the_payload_shape_the_api_returns() -> None:
    """``dump_quiz`` returns the exact payload keys the route serialises.

    Mutation that breaks it: dropping a key from ``to_payload`` (the API
    response model would then invent a default and the client would misread it).
    """
    generator = ClozeQuizGenerator(_quiz_corpus())
    questions = generator.generate(class_level=6, subject="science", num=3, seed=3)
    assert questions, "the bundled corpus must yield class-6 science questions"
    payload = dump_quiz(questions)
    assert len(payload) == len(questions)
    for item in payload:
        assert set(item) == {"id", "question_text", "options", "answer_index", "chapter", "book"}
        assert "____" in item["question_text"], "the chosen term is blanked in the sentence"
        assert len(item["options"]) == 4
        assert 0 <= item["answer_index"] < 4
        assert len(set(item["options"])) == 4, "options must be distinct, never a duplicate"


def test_second_pass_harvests_more_clozes_than_there_are_chunks() -> None:
    """Requesting more questions than chunks exercises the second-pass harvest.

    Mutation that breaks it: removing the ``if len(questions) < num`` harvest
    block -- a short quiz would silently be returned instead of harvesting
    further clozes from the same chunks.
    """
    corpus = [chunk for chunk in _quiz_corpus() if chunk.meta.class_level == 6][:3]
    generator = ClozeQuizGenerator(corpus)
    questions = generator.generate(class_level=6, num=9, seed=1)
    assert len(questions) > 3, "one question per chunk cannot satisfy num=9"
    assert len({question.id for question in questions}) == len(questions)
    assert len({question.question_text for question in questions}) == len(questions)


def test_second_pass_stops_as_soon_as_the_quota_is_satisfied() -> None:
    """The harvest breaks out of both loops the moment ``num`` is reached.

    Mutation that breaks it: dropping either ``if len(questions) >= num:
    break`` -- the generator would keep harvesting every remaining sentence
    (wasted work, and a quiz longer than the caller asked for).
    """
    corpus = [chunk for chunk in _quiz_corpus() if chunk.meta.class_level == 6][:2]
    generator = ClozeQuizGenerator(corpus)
    questions = generator.generate(class_level=6, num=4, seed=5)
    assert len(questions) == 4, "the harvest must fill the quota and stop"


def test_thin_corpus_returns_what_it_can_instead_of_failing() -> None:
    """A corpus with no usable distractors yields fewer questions, never an error.

    Mutation that breaks it: dropping the ``if distractors is None: continue``
    guard (TypeError on a None distractors list) or the ``_best_cloze`` None
    return (``None`` would be unpacked).
    """
    from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta

    single = Chunk(
        id="only",
        text=BN_SENTENCE,
        meta=CurriculumMeta(
            curriculum_year=2024,
            class_level=6,
            subject=BN["science"],
            book="x",
            source="test",
            chapter=BN["chapter"],
        ),
    )
    assert ClozeQuizGenerator([single]).generate(class_level=6, num=3) == []


def test_terms_outside_the_candidate_rules_are_never_blanked() -> None:
    """Digits, stopwords and 1-2 character tokens are not quiz answers.

    Mutation that breaks it: removing ``_is_candidate``'s length/digit/stopword
    rules -- the generator would blank "এবং" or a page number.
    """
    from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta

    text = "১২৩ ৪৫ \u098f\u09ac\u0982 \u0995\u09bf \u0985 \u0995"
    chunk = Chunk(
        id="noise",
        text=text,
        meta=CurriculumMeta(
            curriculum_year=2024,
            class_level=6,
            subject="x",
            book="x",
            source="test",
            chapter="x",
        ),
    )
    generator = ClozeQuizGenerator([chunk])
    assert generator.chunk_terms[0] == set()
    assert generator.generate(class_level=6, num=3) == []


# ── services/retention.py ─────────────────────────────────────────────────


def _retention_settings(**over):
    from bangla_gpt_api.config import Settings

    base = dict(env="test", jwt_secret="x" * 40, chat_retention_days=30)
    base.update(over)
    return Settings(**base)


def test_sweep_deletes_expired_tokens_and_used_invites_only(db) -> None:
    """Token grace window: only rows past expiry + 30 days are swept, and only
    *used* invites.

    Mutation that breaks it: swapping ``< token_cutoff`` for ``>``, or dropping
    the ``used_at.isnot(None)`` condition on invites (unused codes would be
    deleted and a pending parent link would silently disappear).
    """
    user = make_user(db)
    student = make_student(db)
    now = utcnow()
    stale = now - timedelta(days=retention.TOKEN_GRACE_DAYS + 5)
    fresh = now - timedelta(days=1)

    db.add_all(
        [
            PasswordReset(user_id=user.id, token_hash="1" * 64, expires_at=stale),
            PasswordReset(user_id=user.id, token_hash="2" * 64, expires_at=fresh),
            EmailVerification(user_id=user.id, token_hash="3" * 64, expires_at=stale),
            ParentInvite(student_id=student.id, code_hash="4" * 64, expires_at=stale),
            ParentInvite(student_id=student.id, code_hash="5" * 64, expires_at=stale, used_at=now),
        ]
    )
    db.commit()

    report = retention.run_retention_sweep(db, settings=_retention_settings(), now=now)
    assert report["password_resets_deleted"] == 1
    assert report["email_verifications_deleted"] == 1
    assert report["used_invites_deleted"] == 1

    remaining_resets = set(db.execute(select(PasswordReset.token_hash)).scalars())
    assert remaining_resets == {"2" * 64}
    remaining_invites = set(db.execute(select(ParentInvite.code_hash)).scalars())
    assert remaining_invites == {"4" * 64}, "the unused invite must survive"


def test_sweep_deletes_old_analytics_events_and_keeps_recent_ones(db) -> None:
    """Analytics events follow their own window (F-058).

    Mutation that breaks it: removing the analytics DELETE (the trail would
    grow without bound and outlive the retention policy it claims to follow).
    """
    now = utcnow()
    db.add_all(
        [
            AnalyticsEventRow(name="old", props={}, created_at=now - timedelta(days=200)),
            AnalyticsEventRow(name="new", props={}, created_at=now - timedelta(days=1)),
        ]
    )
    db.commit()

    report = retention.run_retention_sweep(
        db, settings=_retention_settings(analytics_retention_days=180), now=now
    )
    assert report["analytics_events_deleted"] == 1
    assert set(db.execute(select(AnalyticsEventRow.name)).scalars()) == {"new"}


def test_sweep_with_a_message_less_conversation_skips_the_feedback_detach(db) -> None:
    """``_detach_feedback_from_messages`` has a "no messages" branch.

    A conversation can be old and empty (created, never used). The sweep must
    delete it without touching feedback. Mutation that breaks it: dropping the
    ``if message_ids:`` guard -- the update statement would run with an empty
    ``IN ()``.
    """
    student = make_student(db)
    now = utcnow()
    empty = Conversation(student_id=student.id, title="empty", created_at=now - timedelta(days=90))
    db.add(empty)
    db.commit()
    empty_id = empty.id

    report = retention.run_retention_sweep(db, settings=_retention_settings(), now=now)
    assert report["conversations_deleted"] == 1
    assert report["chat_messages_deleted"] == 0
    assert (
        db.execute(select(Conversation.id).where(Conversation.id == empty_id)).scalar_one_or_none()
        is None
    )


def test_sweep_dry_run_is_a_pure_read_at_the_same_instant(db) -> None:
    """dry_run reports the same counts it would delete, and deletes nothing.

    Mutation that breaks it: performing the deletes before the ``if dry_run``
    return (the compliance-evidence path would destroy data).
    """
    student = make_student(db)
    now = utcnow()
    conversation = Conversation(
        student_id=student.id, title="old", created_at=now - timedelta(days=90)
    )
    db.add(conversation)
    db.commit()
    message = ChatMessage(conversation_id=conversation.id, role="user", content=BN_SENTENCE)
    db.add(message)
    db.commit()
    conversation_id = conversation.id

    dry = retention.run_retention_sweep(db, settings=_retention_settings(), dry_run=True, now=now)
    assert dry["conversations_deleted"] == 1 and dry["chat_messages_deleted"] == 1
    assert (
        db.execute(select(Conversation.id).where(Conversation.id == conversation_id)).scalar_one()
        == conversation_id
    )

    real = retention.run_retention_sweep(db, settings=_retention_settings(), now=now)
    assert real["conversations_deleted"] == 1 and real["chat_messages_deleted"] == 1


def test_retention_report_counts_match_what_the_sweep_deletes(db) -> None:
    """The report is the contract the audit trail records: counts must agree.

    Mutation that breaks it: computing the report AFTER the deletes (every
    count would read zero and the audit row would understate the sweep).
    """
    student = make_student(db)
    now = utcnow()
    old = Conversation(student_id=student.id, title="old", created_at=now - timedelta(days=90))
    recent = Conversation(student_id=student.id, title="recent", created_at=now - timedelta(days=2))
    db.add_all([old, recent])
    db.commit()

    report_before = retention.retention_report(db, now=now, chat_retention_days=30)
    sweep = retention.run_retention_sweep(db, settings=_retention_settings(), now=now)
    assert sweep["conversations_deleted"] == report_before["conversations_deleted"] == 1
    assert sweep["conversations_deleted"] == report_before["chat_messages_deleted"] + 1


def test_retention_token_grace_constant_is_thirty_days() -> None:
    """The 30-day audit/replay window is a documented policy constant.

    Mutation that breaks it: lowering TOKEN_GRACE_DAYS (reset tokens would be
    purged inside the replay window the policy promises).
    """
    assert retention.TOKEN_GRACE_DAYS == 30


def test_student_rows_are_not_touched_by_any_sweep(db) -> None:
    """Retention is chat/token/analytics only: a learner's profile survives.

    Mutation that breaks it: adding a table to the sweep that holds profiles
    (a real product incident, not a style issue).
    """
    student = make_student(db)
    retention.run_retention_sweep(
        db, settings=_retention_settings(), now=utcnow() + timedelta(days=4000)
    )
    assert db.get(Student, student.id) is not None


def test_unused_student_invite_rows_are_out_of_scope(db) -> None:
    """``StudentInvite`` (class-import codes) is not swept: the handout may
    still be unused. Asserted so a future sweep cannot silently invalidate
    printed codes the school has not handed out yet."""
    from bangla_gpt_api.db.models import ClassRoom, School

    school = School(name="s", code="S-1")
    db.add(school)
    db.commit()
    room = ClassRoom(school_id=school.id, class_level=6, section="A")
    db.add(room)
    db.commit()
    student = make_student(db)
    invite = StudentInvite(
        code_hash="9" * 64,
        email="pending@example.test",
        classroom_id=room.id,
        student_id=student.id,
        expires_at=utcnow() - timedelta(days=400),
    )
    db.add(invite)
    db.commit()
    retention.run_retention_sweep(
        db, settings=_retention_settings(), now=utcnow() + timedelta(days=4000)
    )
    assert db.get(StudentInvite, invite.id) is not None
