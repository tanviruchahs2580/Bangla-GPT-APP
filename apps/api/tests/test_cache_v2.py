"""S5.3: shared caches -- MemoryCache semantics, CachedRankingIndex transparency,
build_cache switching, fail-soft Redis behaviour, per-user summary caching,
and (when REDIS_URL points at a real Redis) cross-instance consistency.
"""

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

import bangla_gpt_api.main as bgpt_main
from bangla_gpt_api.caching import (
    CachedRankingIndex,
    MemoryCache,
    RedisCache,
    build_cache,
)
from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.main import create_app
from bangla_gpt_api.ratelimit import RedisRateLimiter
from bangla_gpt_api.retrieval.bm25 import Hit

PASSWORD = "supersecret1"
REDIS_URL = os.environ.get("REDIS_URL")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="REDIS_URL not set")


def _chunk(idx: int, class_level: int = 6) -> Chunk:
    return Chunk.model_validate(
        {
            "id": f"c{idx}",
            "text": f"chunk text {idx}",
            "meta": {
                "curriculum_year": 2024,
                "class_level": class_level,
                "subject": "science",
                "book": "test-book",
                "source": "unit",
                "chapter": f"chapter-{idx}",
            },
        }
    )


class FakeIndex:
    """Minimal RankingIndex stand-in counting real (uncached) searches."""

    def __init__(self) -> None:
        self.calls = 0
        self.chunks = [_chunk(1)]

    def search(
        self, query, *, class_level=None, subject=None, chapter=None, top_k=4, min_score=0.0
    ):
        self.calls += 1
        return [Hit(chunk=_chunk(class_level or 0), score=1.5)]


def _settings(tmp_path, **kw) -> Settings:
    base = dict(
        env="test",
        database_url=f"sqlite:///{tmp_path}/cache.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    base.update(kw)
    return Settings(**base)


# --------------------------------------------------------------------------
# MemoryCache semantics
# --------------------------------------------------------------------------


def test_memory_cache_roundtrip_and_miss():
    c = MemoryCache()
    assert c.get_json("missing") is None
    c.set_json("k", {"a": [1, 2]}, ttl=30)
    assert c.get_json("k") == {"a": [1, 2]}


def test_memory_cache_ttl_expiry():
    c = MemoryCache()
    c.set_json("k", 1, ttl=0.05)
    assert c.get_json("k") == 1
    time.sleep(0.08)
    assert c.get_json("k") is None


def test_memory_cache_returns_deep_copies():
    c = MemoryCache()
    c.set_json("k", {"v": [1]}, ttl=30)
    got = c.get_json("k")
    got["v"].append(99)
    assert c.get_json("k") == {"v": [1]}


def test_memory_cache_bounded_eviction():
    c = MemoryCache(max_keys=2)
    c.set_json("a", 1, ttl=30)
    time.sleep(0.01)
    c.set_json("b", 2, ttl=30)
    time.sleep(0.01)
    c.set_json("c", 3, ttl=30)
    assert c.get_json("a") is None  # oldest expiry evicted
    assert c.get_json("b") == 2
    assert c.get_json("c") == 3


# --------------------------------------------------------------------------
# build_cache switching (one infra switch, S5.1)
# --------------------------------------------------------------------------


def test_build_cache_defaults_to_memory(tmp_path):
    assert isinstance(build_cache(_settings(tmp_path)), MemoryCache)


def test_build_cache_redis_requires_url(tmp_path):
    s = _settings(tmp_path, rate_limit_backend="redis", redis_url=None)
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        build_cache(s)


def test_build_cache_redis_backend_selects_shared_cache(tmp_path):
    s = _settings(tmp_path, rate_limit_backend="redis", redis_url="redis://127.0.0.1:1/0")
    # from_url is lazy: constructing must not connect.
    assert isinstance(build_cache(s), RedisCache)


def test_redis_cache_is_fail_soft_when_server_down():
    c = RedisCache("redis://127.0.0.1:1/0")  # refused instantly, no server
    assert c.get_json("any") is None  # degrades to miss
    c.set_json("any", {"x": 1}, ttl=5)  # must not raise
    c.clear()  # must not raise


# --------------------------------------------------------------------------
# CachedRankingIndex transparency
# --------------------------------------------------------------------------


def test_cached_index_serves_repeat_from_cache():
    inner = FakeIndex()
    idx = CachedRankingIndex(inner, MemoryCache())
    h1 = idx.search("kox ki", class_level=6)
    h2 = idx.search("kox ki", class_level=6)
    assert inner.calls == 1  # second call never hit the index
    assert [h.chunk.id for h in h1] == [h.chunk.id for h in h2]
    assert h2[0].score == pytest.approx(1.5)


def test_cached_index_preserves_class_scope_isolation():
    inner = FakeIndex()
    idx = CachedRankingIndex(inner, MemoryCache())
    h8 = idx.search("same query", class_level=8)
    h10 = idx.search("same query", class_level=10)
    assert inner.calls == 2  # class is part of the key -- no cross-class leak
    assert h8[0].chunk.id == "c8"
    assert h10[0].chunk.id == "c10"


def test_cached_index_hit_fidelity_roundtrip():
    inner = FakeIndex()
    idx = CachedRankingIndex(inner, MemoryCache())
    idx.search("q", class_level=6, subject="science", top_k=2, min_score=0.5)
    (hit,) = idx.search("q", class_level=6, subject="science", top_k=2, min_score=0.5)
    assert hit.chunk.text == "chunk text 6"
    assert hit.chunk.meta.class_level == 6
    assert hit.chunk.meta.chapter == "chapter-6"
    assert hit.chunk.meta.model_dump()["curriculum_year"] == 2024


def test_cached_index_caches_empty_results():
    class EmptyIndex(FakeIndex):
        def search(self, *a, **k):
            self.calls += 1
            return []

    inner = EmptyIndex()
    idx = CachedRankingIndex(inner, MemoryCache())
    assert idx.search("nothing matches") == []
    assert idx.search("nothing matches") == []
    assert inner.calls == 1


def test_cached_index_query_never_in_key_plaintext(monkeypatch):
    seen: list[str] = []
    spy = MemoryCache()
    orig_set = spy.set_json

    def spy_set(key, value, ttl):
        seen.append(key)
        return orig_set(key, value, ttl)

    monkeypatch.setattr(spy, "set_json", spy_set)
    idx = CachedRankingIndex(FakeIndex(), spy)
    idx.search("personal question about rahi", class_level=6)
    assert seen and all("rahi" not in k for k in seen)  # R11: hashed keys


# --------------------------------------------------------------------------
# /dashboard/summary 60s cache (spec: 60-second TTL, per user)
# --------------------------------------------------------------------------


def _register_login(client, email):
    client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Cache",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    tok = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {tok}"}


def test_dashboard_summary_cached_for_60s(tmp_path, monkeypatch):
    monkeypatch.setattr(bgpt_main.caching, "SUMMARY_CACHE_TTL_SECONDS", 60.0)
    calls = {"n": 0}
    # ARCH-001: patch weak_names at its canonical home (services.weakness);
    # routers call it via module attribute, so this covers every caller.
    from bangla_gpt_api.services import weakness as weakness_svc

    orig = weakness_svc.weak_names

    def counting(db, sid):
        calls["n"] += 1
        return orig(db, sid)

    monkeypatch.setattr(weakness_svc, "weak_names", counting)
    c = TestClient(create_app(_settings(tmp_path)))
    h = _register_login(c, "cache1@example.com")
    r1 = c.get("/dashboard/summary", headers=h)
    assert r1.status_code == 200
    assert calls["n"] == 1
    r2 = c.get("/dashboard/summary", headers=h)
    assert r2.json() == r1.json()
    assert calls["n"] == 1  # second call answered from cache
    # Another user must NOT share the cache entry.
    h2 = _register_login(c, "cache2@example.com")
    c.get("/dashboard/summary", headers=h2)
    assert calls["n"] == 2  # recomputed for a different user
    # Entry evicted (what the 60s TTL expiry does) -> recompute, same payload.
    c.app.state.cache.clear()
    r3 = c.get("/dashboard/summary", headers=h)
    assert r3.json() == r1.json()
    assert calls["n"] == 3


def test_dashboard_summary_memory_cache_attached(tmp_path):
    c = TestClient(create_app(_settings(tmp_path)))
    assert isinstance(c.app.state.cache, MemoryCache)


def test_cache_hit_metrics_visible_on_metrics_endpoint(tmp_path):
    """S5.3 PASS-WHEN: cache-hit metrics visible (scrape /metrics)."""
    c = TestClient(create_app(_settings(tmp_path)))
    h = _register_login(c, "metrics1@example.com")
    c.get("/dashboard/summary", headers=h)  # miss
    c.get("/dashboard/summary", headers=h)  # hit
    c.get("/search", params={"q": "science"}, headers=h)  # rag miss
    c.get("/search", params={"q": "science"}, headers=h)  # rag hit
    body = c.get("/metrics").text
    assert 'bgpt_cache_events_total{cache="summary",result="miss"}' in body
    assert 'bgpt_cache_events_total{cache="summary",result="hit"}' in body
    assert 'bgpt_cache_events_total{cache="rag",result="miss"}' in body
    assert 'bgpt_cache_events_total{cache="rag",result="hit"}' in body


# --------------------------------------------------------------------------
# Real Redis (skip unless REDIS_URL): shared cache + cross-instance limiter
# --------------------------------------------------------------------------


@needs_redis
def test_redis_cache_roundtrip_and_ttl():
    c = RedisCache(REDIS_URL)
    key = f"bgpt-test:{uuid.uuid4().hex}"
    assert c.get_json(key) is None
    c.set_json(key, {"v": [1, 2], "s": "x"}, ttl=30)
    assert c.get_json(key) == {"v": [1, 2], "s": "x"}
    c.set_json(key + ":ttl", 1, ttl=1)
    time.sleep(1.4)
    assert c.get_json(key + ":ttl") is None


@needs_redis
def test_redis_limiter_shared_across_two_instances():
    """Two limiter objects = two pods: the window limit must be GLOBAL."""
    url = REDIS_URL
    prefix = f"podtest-{uuid.uuid4().hex[:8]}"
    pod_a = RedisRateLimiter(url)
    pod_b = RedisRateLimiter(url)
    limit = 10
    allowed = 0
    for _ in range(6):
        allowed += pod_a.check(f"{prefix}:u", limit)
    for _ in range(4):
        allowed += pod_b.check(f"{prefix}:u", limit)
    assert allowed == 10  # first 10 across BOTH pods pass
    assert pod_a.check(f"{prefix}:u", limit) is False  # 11th denied...
    assert pod_b.check(f"{prefix}:u", limit) is False  # ...on either pod


@needs_redis
def test_cached_ranking_index_shares_hits_across_instances():
    url = REDIS_URL
    shared = RedisCache(url)
    tag = uuid.uuid4().hex[:8]
    inner_a = FakeIndex()
    inner_b = FakeIndex()
    qa = CachedRankingIndex(inner_a, shared)
    qb = CachedRankingIndex(inner_b, shared)
    query = f"shared-query-{tag}"  # unique: cannot collide with a previous run
    qa.search(query, class_level=6)
    assert inner_a.calls == 1
    qb.search(query, class_level=6)
    assert inner_b.calls == 0  # pod B reused pod A's retrieval result
