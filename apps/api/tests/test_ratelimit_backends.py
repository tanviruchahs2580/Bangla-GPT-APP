"""B8 — rate limiter backends."""

import time

import pytest

from bangla_gpt_api.ratelimit import (
    MemoryRateLimiter,
    RateLimitBackendError,
    RedisRateLimiter,
)


def test_memory_limiter_enforces_window() -> None:
    limiter = MemoryRateLimiter()
    for _ in range(3):
        assert limiter.check("k", 3) is True
    assert limiter.check("k", 3) is False
    assert limiter.check("other", 3) is True


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.store: dict[str, int] = {}
        self.fail = fail

    def incr(self, name: str) -> int:
        if self.fail:
            raise RuntimeError("boom")
        self.store[name] = self.store.get(name, 0) + 1
        return self.store[name]

    def expire(self, name: str, ttl: int) -> None:
        self.store[f"ttl:{name}"] = ttl


def test_redis_limiter_fixed_window(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = RedisRateLimiter("redis://localhost:6379/0")
    fake = FakeRedis()
    monkeypatch.setattr(limiter, "_redis", fake)

    assert limiter.check("login|1.2.3.4", 2) is True
    assert limiter.check("login|1.2.3.4", 2) is True
    assert limiter.check("login|1.2.3.4", 2) is False
    # a different minute window resets the counter
    monkeypatch.setattr(time, "time", lambda: 3600.0)
    assert limiter.check("login|1.2.3.4", 2) is True


def test_redis_fail_open_and_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import redis.exceptions

    open_limiter = RedisRateLimiter("redis://localhost:6379/0", fail_open=True)
    closed_limiter = RedisRateLimiter("redis://localhost:6379/0", fail_open=False)

    class DeadClient:
        @staticmethod
        def incr(name):
            raise redis.exceptions.ConnectionError("down")

        @staticmethod
        def expire(name, ttl):
            raise redis.exceptions.ConnectionError("down")

    monkeypatch.setattr(open_limiter, "_redis", DeadClient())
    monkeypatch.setattr(closed_limiter, "_redis", DeadClient())

    assert open_limiter.check("k", 5) is True  # fail-open allows
    with pytest.raises(RateLimitBackendError):
        closed_limiter.check("k", 5)  # fail-closed raises → API answers 503


def test_app_answers_503_when_backend_down_and_fail_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    import bangla_gpt_api.main as main_module
    from bangla_gpt_api.config import Settings

    class DeadLimiter(MemoryRateLimiter):
        def check(self, key: str, limit: int) -> bool:
            raise RateLimitBackendError("unreachable")

    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/rl.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        rate_limit_backend="redis",
        redis_url="redis://localhost:6379/0",
        rate_limit_fail_open=False,
    )
    monkeypatch.setattr(main_module, "build_limiter", lambda s: DeadLimiter())

    client = TestClient(main_module.create_app(settings))
    limited = client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
    assert limited.status_code == 503
