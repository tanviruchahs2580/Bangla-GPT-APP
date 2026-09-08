"""S5.3 shared caches: per-user dashboard summary + RAG query results.

Same infra switch as the rate limiter: ``RATE_LIMIT_BACKEND=redis`` +
``REDIS_URL`` puts the caches in Redis so every worker/pod shares them;
without Redis the identical API runs on a bounded in-process memory cache.
A cache must never take the site down, so every Redis failure degrades to
a miss (logged as a count-free warning, R11: no payload in logs).

Key hygiene (R11): callers pass already-safe keys; the RAG wrapper hashes
the raw query with SHA-256 so learner questions never appear verbatim in
Redis key-space. Cached VALUES are curriculum chunks / aggregate stats --
never message content or PII.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
import time
from typing import Any, Protocol

from prometheus_client import Counter

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.metrics import REGISTRY
from bangla_gpt_api.retrieval.bm25 import Hit

logger = logging.getLogger(__name__)

# S5.3 PASS-WHEN: cache-hit metrics visible (scrape /metrics).
CACHE_EVENTS_TOTAL = Counter(
    "bgpt_cache_events_total",
    "Cache lookups by logical cache and result.",
    labelnames=["cache", "result"],
    registry=REGISTRY,
)

# Spec: /dashboard/summary is served from cache for 60s per user.
SUMMARY_CACHE_TTL_SECONDS = 60.0
# Corpus is static per boot (loaded at startup), so retrieval results are
# safe to share for minutes; keep modest so a hot-fix restart still wins.
RAG_CACHE_TTL_SECONDS = 300.0


class Cache(Protocol):
    def get_json(self, key: str) -> Any: ...

    def set_json(self, key: str, value: Any, ttl: float) -> None: ...

    def clear(self) -> None: ...

    def ping(self) -> bool:
        """Backend liveness (S5.10 /status); never raises."""
        ...


class MemoryCache:
    """TTL cache with a bounded key space (mirrors MemoryRateLimiter's spirit).

    Values are deep-copied in and out so a caller mutating a returned object
    cannot corrupt what the next caller reads.
    """

    def __init__(self, max_keys: int = 10_000) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._max_keys = max_keys
        self._lock = threading.Lock()

    def get_json(self, key: str) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                del self._data[key]
                return None
            return copy.deepcopy(value)

    def set_json(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            if len(self._data) >= self._max_keys and key not in self._data:
                now = time.monotonic()
                expired = [k for k, (exp, _) in self._data.items() if exp <= now]
                for k in expired:
                    del self._data[k]
                while len(self._data) >= self._max_keys:
                    oldest = min(self._data, key=lambda k: self._data[k][0])
                    del self._data[oldest]
            self._data[key] = (time.monotonic() + ttl, copy.deepcopy(value))

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def ping(self) -> bool:
        return True


class RedisCache:
    """Shared cache over Redis. Redis down => behave like an empty cache."""

    def __init__(self, url: str) -> None:
        import redis  # declared hard dependency, lazy import like the limiter

        self._redis: redis.Redis = redis.Redis.from_url(
            url, socket_connect_timeout=1.0, socket_timeout=1.0, decode_responses=True
        )

    def get_json(self, key: str) -> Any:
        import redis.exceptions

        try:
            raw = self._redis.get(key)
        except redis.exceptions.RedisError:
            logger.warning("cache_backend_unreachable", extra={"op": "get"})
            return None
        if raw is None:
            return None
        # redis-py types get() as str | Awaitable[str] (pipeline mode); this
        # client is plain sync Redis, and anything non-string is treated as
        # the same unparsable miss as a malformed payload below.
        if not isinstance(raw, (str, bytes, bytearray)):
            return None
        try:
            return json.loads(raw)
        except ValueError:
            logger.warning("cache_value_unparsable", extra={"op": "get"})
            return None

    def set_json(self, key: str, value: Any, ttl: float) -> None:
        import redis.exceptions

        try:
            self._redis.set(key, json.dumps(value), ex=max(1, int(ttl)))
        except (redis.exceptions.RedisError, TypeError, ValueError):
            # TypeError/ValueError: value not JSON-serialisable -> skip cache.
            logger.warning("cache_write_failed", extra={"op": "set"})

    def clear(self) -> None:
        logger.warning("cache_clear_skipped_on_shared_backend", extra={"op": "clear"})

    def ping(self) -> bool:
        import redis.exceptions

        try:
            return bool(self._redis.ping())
        except redis.exceptions.RedisError:
            return False


def build_cache(settings: Any) -> Cache:
    """One infra switch (S5.1): backend=redis + REDIS_URL -> shared caches."""
    from bangla_gpt_api.config import Settings

    if not isinstance(settings, Settings):
        raise TypeError("build_cache expects a Settings instance")
    if settings.rate_limit_backend.strip().lower() == "redis":
        if not settings.redis_url:
            raise ValueError("redis backend requires REDIS_URL")
        return RedisCache(settings.redis_url)
    return MemoryCache()


class CachedRankingIndex:
    """Transparent Cache decorator over any RankingIndex (S5.3).

    Retrieval answers depend only on (query, class, subject, chapter, top_k,
    min_score) and the immutable boot-time corpus, so the whole result list
    is cacheable. The query goes into the key as SHA-256 (R11). Class-scope
    isolation is preserved: class/subject are part of the key, so a class-8
    hit list can never answer a class-10 query (S4.3 lesson).
    """

    def __init__(self, inner: Any, cache: Cache, ttl: float = RAG_CACHE_TTL_SECONDS) -> None:
        self.inner = inner
        self._cache = cache
        self._ttl = ttl
        # Corpus is fixed at build time; share the list so the RankingIndex
        # protocol attribute (read/write) stays satisfied for type-checkers.
        self.chunks: list[Chunk] = inner.chunks

    def search(
        self,
        query: str,
        *,
        class_level: int | None = None,
        subject: str | None = None,
        chapter: str | None = None,
        top_k: int = 4,
        min_score: float = 0.0,
    ) -> list[Hit]:
        digest = hashlib.sha256(
            f"{query}|{class_level}|{subject}|{chapter}|{top_k}|{min_score}".encode()
        ).hexdigest()
        key = f"rag:{digest}"
        cached = self._cache.get_json(key)
        if cached is not None:
            try:
                hits = [
                    Hit(chunk=Chunk(**row["chunk"]), score=float(row["score"])) for row in cached
                ]
            except (KeyError, TypeError, ValueError):
                logger.warning("cache_value_unparsable", extra={"op": "rag"})
            else:
                CACHE_EVENTS_TOTAL.labels(cache="rag", result="hit").inc()
                return hits
        CACHE_EVENTS_TOTAL.labels(cache="rag", result="miss").inc()
        hits = self.inner.search(
            query,
            class_level=class_level,
            subject=subject,
            chapter=chapter,
            top_k=top_k,
            min_score=min_score,
        )
        self._cache.set_json(
            key,
            [{"chunk": h.chunk.model_dump(mode="json"), "score": h.score} for h in hits],
            self._ttl,
        )
        return hits
