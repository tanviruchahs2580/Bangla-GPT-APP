"""Pluggable rate-limiting backends.

``memory`` – sliding window, per-process (default; dev/small deployments).
``redis`` – fixed-window INCR/EXPIRE counters shared by all workers/pods,
              so limits survive horizontal scaling. If Redis is unreachable
              the limiter either fails open (allow) or closed (raise),
              controlled by ``RATE_LIMIT_FAIL_OPEN``.

The module also owns the CONCURRENCY limiter (AUD-A2-10 / A7-05): a
request-rate limit does not bound how many generations one identity has in
flight, and each in-flight generation is a provider connection and a bill.
Concurrency slots are counted in the same pluggable backend, with a safety
TTL so a crashed worker cannot leak a slot forever.
"""

import logging
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol, cast

logger = logging.getLogger(__name__)


class ConcurrencyLimitExceeded(RuntimeError):
    """Raised when an identity already has its maximum generations in flight."""


#: Connect/read timeout for every Redis call (limiter, concurrency, cache).
#: 1.0 s failed closed on a measured 0.1-1.0 s TCP handshake to a
#: port-forwarded Redis behind Docker Desktop (replica_check, 2026-10-19): a
#: request burst right after a cold start turned healthy traffic into 503s.
#: Two seconds still bounds the failure latency, and an unreachable backend
#: keeps its documented posture (fail closed for the limiter, miss for the
#: cache).
REDIS_SOCKET_TIMEOUT_SECONDS = 2.0

#: Safety TTL for a concurrency slot: refreshed on every acquire, so a normal
#: turn (bounded by the worker timeout) never expires it, while a worker that
#: dies mid-turn stops inflating the counter after this long.
CONCURRENCY_SLOT_TTL_SECONDS = 300


class RateLimitBackendError(RuntimeError):
    """Raised when the configured backend cannot be reached (fail-closed)."""


class RateLimiter(Protocol):
    def check(self, key: str, limit: int) -> bool:
        """Return True when the request is allowed under ``limit``/minute."""
        ...


class MemoryRateLimiter:
    """Sliding-window limiter with a bounded key space.

    ``max_keys`` bounds memory when unique IPs/keys churn (national-scale
    traffic behind one proxy): once exceeded, keys with no hits inside the
    60s window are evicted, then the least-recently-hit keys are dropped.
    """

    def __init__(self, max_keys: int = 10_000) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._max_keys = max_keys

    def _evict(self, now: float) -> None:
        if len(self._hits) < self._max_keys:
            return
        stale = [k for k, dq in self._hits.items() if not dq or now - dq[-1] >= 60.0]
        for k in stale:
            del self._hits[k]
        # Make room for the key about to be inserted so len never exceeds
        # max_keys after check completes.
        if len(self._hits) >= self._max_keys:
            overflow = sorted(self._hits.items(), key=lambda kv: kv[1][-1])
            for k, _ in overflow[: len(self._hits) - self._max_keys + 1]:
                del self._hits[k]

    def check(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        self._evict(now)
        hits = self._hits[key]
        while hits and now - hits[0] >= 60.0:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


class RedisRateLimiter:
    def __init__(self, url: str, *, fail_open: bool = False) -> None:
        import redis  # imported lazily; declared as a hard dependency

        self._fail_open = fail_open
        self._redis: redis.Redis = redis.Redis.from_url(
            url,
            socket_connect_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
            socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
            decode_responses=True,
        )

    def check(self, key: str, limit: int) -> bool:
        import redis.exceptions

        window = int(time.time() // 60)
        name = f"rl:{key}:{window}"
        try:
            # redis-py types incr as int | Awaitable[int] (pipeline mode);
            # this client is plain sync Redis, so the value is always an int.
            count = int(cast(int, self._redis.incr(name)))
            if count == 1:
                self._redis.expire(name, 75)
            return int(count) <= limit
        except redis.exceptions.RedisError:
            logger.warning("rate_limit_backend_unreachable", extra={"backend": "redis"})
            if self._fail_open:
                return True
            raise RateLimitBackendError("Redis rate-limit backend unreachable") from None


class ConcurrencyLimiter(Protocol):
    """Counts in-flight work per identity (A7-05 concurrency cap)."""

    def acquire(self, key: str, limit: int) -> bool:
        """Take a slot for ``key``; False when ``limit`` is already in flight."""
        ...

    def release(self, key: str) -> None:
        """Give the slot back (idempotent, never raises)."""
        ...


class MemoryConcurrencyLimiter:
    """Per-process in-flight counter with a safety TTL.

    Slot bookkeeping survives a crashed *turn* (the TTL) but not a crashed
    process; deployments with more than one replica must use the Redis
    backend so a slot taken on one replica is visible on the others.
    """

    def __init__(self, slot_ttl: float = CONCURRENCY_SLOT_TTL_SECONDS) -> None:
        import threading

        self._slots: dict[str, tuple[int, float]] = {}
        self._ttl = slot_ttl
        self._lock = threading.Lock()

    def _sweep(self, now: float) -> None:
        expired = [k for k, (_, expires) in self._slots.items() if expires <= now]
        for key in expired:
            del self._slots[key]

    def acquire(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            count, _ = self._slots.get(key, (0, 0.0))
            if count >= limit:
                return False
            self._slots[key] = (count + 1, now + self._ttl)
            return True

    def release(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            count, _ = self._slots.get(key, (0, 0.0))
            if count <= 1:
                self._slots.pop(key, None)
            else:
                self._slots[key] = (count - 1, now + self._ttl)


class RedisConcurrencyLimiter:
    """Shared in-flight counter (INCR/DECR with a refreshing TTL).

    Redis unreachable: fail closed by default (``fail_open=False``) — an
    unknown concurrency state must not be treated as "no work in flight",
    because that is exactly the abuse the cap exists for.
    """

    def __init__(self, url: str, *, fail_open: bool = False) -> None:
        import redis  # imported lazily; declared as a hard dependency

        self._fail_open = fail_open
        self._redis: redis.Redis = redis.Redis.from_url(
            url,
            socket_connect_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
            socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
            decode_responses=True,
        )

    @staticmethod
    def _name(key: str) -> str:
        return f"cc:{key}"

    def acquire(self, key: str, limit: int) -> bool:
        import redis.exceptions

        name = self._name(key)
        try:
            count = int(cast(int, self._redis.incr(name)))
            self._redis.expire(name, CONCURRENCY_SLOT_TTL_SECONDS)
            if count <= limit:
                return True
            # over the cap: give the slot straight back, never leave it held
            self._redis.decr(name)
            return False
        except redis.exceptions.RedisError:
            logger.warning("concurrency_backend_unreachable", extra={"backend": "redis"})
            if self._fail_open:
                return True
            raise RateLimitBackendError("Redis concurrency backend unreachable") from None

    def release(self, key: str) -> None:
        import redis.exceptions

        name = self._name(key)
        try:
            remaining = int(cast(int, self._redis.decr(name)))
            if remaining <= 0:
                self._redis.delete(name)
        except redis.exceptions.RedisError:
            logger.warning("concurrency_release_failed", extra={"backend": "redis"})
            if not self._fail_open:
                raise RateLimitBackendError("Redis concurrency backend unreachable") from None


def build_concurrency_limiter(settings: object) -> ConcurrencyLimiter:
    """Build the in-flight limiter on the same backend as the rate limiter."""
    from bangla_gpt_api.config import Settings

    if not isinstance(settings, Settings):
        raise TypeError("build_concurrency_limiter expects a Settings instance")
    if settings.rate_limit_backend == "redis":
        if not settings.redis_url:
            raise ValueError("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
        return RedisConcurrencyLimiter(settings.redis_url, fail_open=settings.rate_limit_fail_open)
    return MemoryConcurrencyLimiter()


@contextmanager
def concurrency_slot(limiter: ConcurrencyLimiter, key: str, limit: int) -> Iterator[None]:
    """Hold one slot for the duration of the block.

    Raises :class:`ConcurrencyLimitExceeded` when the cap is reached; always
    releases on exit, including on exceptions and cancellation.
    """
    if limit <= 0:
        yield
        return
    if not limiter.acquire(key, limit):
        raise ConcurrencyLimitExceeded(f"concurrency limit {limit} reached for {key}")
    try:
        yield
    finally:
        limiter.release(key)


def build_limiter(settings) -> RateLimiter:  # noqa: ANN001 (Settings import cycle)
    """Build the counting backend only.

    Rate-limit *rules* (which route, which limit) are owned by
    ``initialize.middleware_stack.build_middleware_stack`` — the limiter
    itself only answers "is this identity within its window".
    """
    from bangla_gpt_api.config import Settings

    if not isinstance(settings, Settings):
        raise TypeError("build_limiter expects a Settings instance")
    if settings.rate_limit_backend == "redis":
        if not settings.redis_url:
            raise ValueError("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
        return RedisRateLimiter(settings.redis_url, fail_open=settings.rate_limit_fail_open)
    return MemoryRateLimiter()
