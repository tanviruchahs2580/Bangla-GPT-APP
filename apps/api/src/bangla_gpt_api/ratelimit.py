"""Pluggable rate-limiting backends (B8).

``memory``  – sliding window, per-process (default; dev/small deployments).
``redis``   – fixed-window INCR/EXPIRE counters shared by all workers/pods,
              so limits survive horizontal scaling. If Redis is unreachable
              the limiter either fails open (allow) or closed (raise),
              controlled by ``RATE_LIMIT_FAIL_OPEN``.
"""

import logging
import time
from collections import defaultdict, deque
from typing import Protocol, cast

logger = logging.getLogger(__name__)


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
        # max_keys after check() completes.
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
            url, socket_connect_timeout=1.0, socket_timeout=1.0, decode_responses=True
        )

    def check(self, key: str, limit: int) -> bool:
        import redis.exceptions

        window = int(time.time() // 60)
        name = f"rl:{key}:{window}"
        try:
            # redis-py types incr() as int | Awaitable[int] (pipeline mode);
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


def build_limiter(settings) -> RateLimiter:  # noqa: ANN001 (Settings import cycle)
    from bangla_gpt_api.config import Settings

    if not isinstance(settings, Settings):
        raise TypeError("build_limiter expects a Settings instance")
    if settings.rate_limit_backend == "redis":
        if not settings.redis_url:
            raise ValueError("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
        return RedisRateLimiter(settings.redis_url, fail_open=settings.rate_limit_fail_open)
    return MemoryRateLimiter()
