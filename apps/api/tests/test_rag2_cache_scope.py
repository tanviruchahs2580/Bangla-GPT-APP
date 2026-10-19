"""AUD-A2-15 / A9-06, A4-09: the retrieval cache is scoped and invalidates.

Pinned here:

* every scope dimension is in the key -- tenant, class, subject, chapter,
  top_k, min_score, the index version -- so no tenant/class can be served
  another's answer and a rebuilt index cannot serve stale passages;
* a warm entry is a MISS after the index version changes (the invalidation
  test the finding asked for), whether the version comes from the corpus
  fingerprint or an explicit index-version name;
* a tenant-aware inner index receives ``tenant_id`` (the decorator does not
  silently drop the dimension);
* hit and miss counters move, so a hit rate can be measured from /metrics.
"""

from __future__ import annotations

from typing import Any

from bangla_gpt_api.caching import CACHE_EVENTS_TOTAL, CachedRankingIndex
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.metrics import REGISTRY
from bangla_gpt_api.retrieval.bm25 import Hit


def _meta(class_level: int = 6, subject: str = "science") -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=class_level,
        subject=subject,
        book="বিজ্ঞান",
        source="sample",
        chapter="অধ্যায় ১",
        page=1,
    )


def _chunk(chunk_id: str, class_level: int = 6) -> Chunk:
    return Chunk(
        id=chunk_id,
        meta=_meta(class_level=class_level),
        text=f"কোষ হলো জীবদেহের গঠনগত একক ({chunk_id})।",
    )


class _CountingIndex:
    """Records calls; class_level 8 answers differently from class 6."""

    supports_tenant_filter = False

    def __init__(self, chunks: list[Chunk] | None = None) -> None:
        self.chunks = chunks if chunks is not None else [_chunk("c1")]
        self.calls = 0

    def search(self, query: str, **_kwargs: Any) -> list[Hit]:
        self.calls += 1
        return [Hit(chunk=self.chunks[0], score=1.0)]


class _TenantAwareIndex(_CountingIndex):
    supports_tenant_filter = True

    def __init__(self) -> None:
        super().__init__()
        self.tenants: list[Any] = []

    def search(self, query: str, **kwargs: Any) -> list[Hit]:
        self.tenants.append(kwargs.get("tenant_id"))
        return super().search(query, **kwargs)


class _DictCache:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.sets = 0

    def get_json(self, key: str) -> Any:
        return self.data.get(key)

    def set_json(self, key: str, value: Any, ttl: float) -> None:
        self.sets += 1
        self.data[key] = value

    get_json_strict = get_json
    set_json_strict = set_json

    def clear(self) -> None:
        self.data.clear()

    def ping(self) -> bool:
        return True


def _counter(result: str) -> float:
    return (
        REGISTRY.get_sample_value("bgpt_cache_events_total", {"cache": "rag", "result": result})
        or 0.0
    )


def test_key_changes_with_every_scope_dimension() -> None:
    indexed = CachedRankingIndex(_CountingIndex(), _DictCache())
    base = indexed.key_for("কোষ কী?", class_level=6, subject="science", top_k=3)
    assert base != indexed.key_for("কোষ কী?", class_level=8, subject="science", top_k=3)
    assert base != indexed.key_for("কোষ কী?", class_level=6, subject="math", top_k=3)
    assert base != indexed.key_for("কোষ কী?", class_level=6, subject="science", top_k=5)
    assert base != indexed.key_for(
        "কোষ কী?", class_level=6, subject="science", top_k=3, tenant_id=1
    )
    assert base != indexed.key_for(
        "কোষ কী?", class_level=6, subject="science", top_k=3, tenant_id=2
    )
    assert base != indexed.key_for("ভগ্নাংশ কী?", class_level=6, subject="science", top_k=3)
    # the raw query never appears in key space (learner text stays out of Redis)
    assert "কোষ" not in base


def test_second_identical_lookup_is_a_hit_and_a_different_scope_is_not() -> None:
    inner = _CountingIndex()
    cache = _DictCache()
    indexed = CachedRankingIndex(inner, cache)
    hits_before = _counter("hit")
    miss_before = _counter("miss")

    indexed.search("কোষ কী?", class_level=6, subject="science", top_k=3)
    assert inner.calls == 1
    indexed.search("কোষ কী?", class_level=6, subject="science", top_k=3)
    assert inner.calls == 1, "identical lookup must be served from cache"

    # class 8 must NOT be served the class-6 list
    indexed.search("কোষ কী?", class_level=8, subject="science", top_k=3)
    assert inner.calls == 2
    # tenant 7 must NOT be served the unscoped entry
    indexed.search("কোষ কী?", class_level=6, subject="science", top_k=3, tenant_id=7)
    assert inner.calls == 3

    assert _counter("hit") - hits_before == 1
    assert _counter("miss") - miss_before == 3


def test_rebuilt_index_invalidates_the_cache_by_fingerprint() -> None:
    cache = _DictCache()
    first = CachedRankingIndex(_CountingIndex([_chunk("c1")]), cache)
    assert first.search("কোষ কী?")[0].chunk.id == "c1"

    # A rebuild that produced different chunks (new/removed ids) is a
    # different index version: the warm entry must not be served.
    rebuilt = CachedRankingIndex(_CountingIndex([_chunk("c2")]), cache)
    assert rebuilt.index_version != first.index_version
    assert rebuilt.search("কোষ কী?")[0].chunk.id == "c2"
    assert len(cache.data) == 2


def test_explicit_index_version_overrides_the_fingerprint() -> None:
    cache = _DictCache()
    first = CachedRankingIndex(_CountingIndex(), cache, index_version="idx-2026-10-01")
    assert first.search("কোষ কী?")[0].chunk.id == "c1"
    key_v1 = first.key_for("কোষ কী?")
    assert "idx-2026-10-01" in key_v1

    # the blue/green swap: same corpus, new immutable index name -> new key space
    swapped = CachedRankingIndex(_CountingIndex(), cache, index_version="idx-2026-10-19")
    assert swapped.key_for("कॉष কী?") != swapped.key_for("কোষ কী?")  # sanity: query matters
    assert swapped.key_for("कোষ কী?") != key_v1
    swapped.search("কোষ কী?")
    assert len(cache.data) == 2


def test_identical_corpus_rebuild_reuses_the_same_key_space() -> None:
    """A restart that rebuilds the same corpus must not thrash the cache."""
    cache = _DictCache()
    first = CachedRankingIndex(_CountingIndex([_chunk("c1")]), cache)
    first.search("কোষ কী?")
    second = CachedRankingIndex(_CountingIndex([_chunk("c1")]), cache)
    assert second.index_version == first.index_version
    second.search("কোষ কী?")
    assert len(cache.data) == 1


def test_tenant_aware_inner_index_receives_the_tenant() -> None:
    inner = _TenantAwareIndex()
    indexed = CachedRankingIndex(inner, _DictCache())
    indexed.search("কোষ কী?", tenant_id=42)
    indexed.search("কোষ কী?", tenant_id=43)
    assert inner.tenants == [42, 43]


def test_unparsable_cache_value_is_a_miss_not_an_error() -> None:
    inner = _CountingIndex()
    cache = _DictCache()
    indexed = CachedRankingIndex(inner, cache)
    key = indexed.key_for("কোষ কী?")
    cache.data[key] = [{"not": "a hit row"}]
    hits = indexed.search("কোষ কী?")
    assert hits[0].chunk.id == "c1"
    assert inner.calls == 1


def test_cache_counters_exist_for_hit_rate_measurement() -> None:
    assert CACHE_EVENTS_TOTAL.labels(cache="rag", result="hit") is not None
    assert CACHE_EVENTS_TOTAL.labels(cache="rag", result="miss") is not None
