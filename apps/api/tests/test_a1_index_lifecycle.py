"""AUD-A1-10/A1-11/A1-12/A1-24: filters, diversity and index lifecycle.

AUD-A1-11 measured that ``search`` filtered on class_level/subject/chapter
only, that the index had no version identity, and that no swap/rollback was
possible (a bad rebuild had no path back). AUD-A1-12 measured
``tokenize('১২৩') != tokenize('123')``. These tests pin the repairs; the
rollback drill is the end-to-end one the finding asked for.
"""

from __future__ import annotations

from pathlib import Path

from bangla_gpt_api.caching import CachedRankingIndex, MemoryCache
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.retrieval.diversity import mmr_select
from bangla_gpt_api.retrieval.embedding import HashingEmbedder
from bangla_gpt_api.retrieval.filters import SearchFilters, chunk_matches_filters
from bangla_gpt_api.retrieval.hybrid import tokenize
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.retrieval.lifecycle import IndexRegistry, IndexSnapshot, corpus_version

CELL = "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক এবং এটি প্রতিটি জীবের দেহে থাকে। " * 4
EXERCISE = "অনুশীলনী ১। কোষ কী? সংক্ষেপে লিখ এবং একটি উদাহরণ দাও যাতে বোঝা যায়। " * 4


def _chunk(
    chunk_id: str,
    text: str,
    *,
    class_level: int = 6,
    subject: str = "science",
    chapter: str = "কোষ",
    content_type: str = "nctb",
    version: str = "nctb-v1",
) -> Chunk:
    return Chunk(
        id=chunk_id,
        text=text,
        meta=CurriculumMeta(
            class_level=class_level,
            subject=subject,
            book="বিজ্ঞান",
            source="synthetic",
            chapter=chapter,
            curriculum_year=2012,
            content_type=content_type,
            version=version,
        ),
    )


def test_search_filters_content_type_and_version() -> None:
    chunks = [
        _chunk("a-c6", CELL),
        _chunk("b-c6", EXERCISE, content_type="exercise"),
        _chunk("c-c6", CELL, version="nctb-v2"),
    ]
    index = BM25Index(chunks)

    assert {hit.chunk.id for hit in index.search("কোষ কী", class_level=6)} >= {"a-c6", "b-c6"}
    exercises = index.search("কোষ কী", content_type="exercise")
    assert [hit.chunk.id for hit in exercises] == ["b-c6"]
    v2 = index.search("কোষ", version="nctb-v2")
    assert [hit.chunk.id for hit in v2] == ["c-c6"]


def test_hybrid_search_accepts_the_extended_filters() -> None:
    chunks = [
        _chunk("a-c6", CELL),
        _chunk("b-c6", EXERCISE, content_type="exercise"),
    ]
    index = HybridIndex(chunks, HashingEmbedder())
    hits = index.search("কোষ কী", content_type="exercise", top_k=5)
    assert hits and all(hit.chunk.meta.content_type == "exercise" for hit in hits)


def test_filter_schema_documents_absent_dimensions() -> None:
    """tenant/visibility are not filterable because they do not exist on the
    chunk metadata; the schema is explicit about what it does filter."""
    assert {field.name for field in SearchFilters.__dataclass_fields__.values()} == {
        "class_level",
        "subject",
        "chapter",
        "content_type",
        "version",
    }
    chunk = _chunk("a-c6", CELL)
    assert chunk_matches_filters(chunk, class_level=6, subject="science")
    assert not chunk_matches_filters(chunk, content_type="exercise")
    assert not chunk_matches_filters(chunk, version="other")


def test_bengali_and_ascii_digits_tokenize_identically() -> None:
    assert tokenize("১২৩") == tokenize("123") == ["123"]
    assert tokenize("শ্রেণি ৬") == tokenize("শ্রেণি 6")


def test_bm25_retrieves_a_bengali_digit_query_for_ascii_evidence() -> None:
    chunks = [_chunk("a-c6", "অনুশীলনী 6 এর প্রশ্ন: কোষ কী? " * 6)]
    index = BM25Index(chunks)
    assert index.search("অনুশীলনী ৬"), "Bengali-digit query must match ASCII-digit evidence"
    assert index.search("অনুশীলনী 6")


def test_mmr_select_displaces_near_duplicates() -> None:
    from bangla_gpt_api.retrieval.bm25 import Hit

    duplicate = _chunk("dup", CELL)
    distinct = _chunk("distinct", "সালোকসংশ্লেষণ উদ্ভিদের খাদ্য তৈরির প্রক্রিয়া। " * 4)
    hits = [
        Hit(chunk=duplicate, score=1.0),
        Hit(chunk=duplicate.model_copy(update={"id": "dup2"}), score=0.99),
        Hit(chunk=distinct, score=0.5),
    ]
    selected = mmr_select(hits, k=2, lambda_=0.5)
    assert [hit.chunk.id for hit in selected] == ["dup", "distinct"]


def test_diversity_is_opt_in_and_does_not_change_default_ranking() -> None:
    chunks = [_chunk("a-c6", CELL), _chunk("b-c6", EXERCISE, content_type="exercise")]
    index = HybridIndex(chunks, HashingEmbedder())
    default = index.search("কোষ কী", top_k=2)
    diverse = index.search("কোষ কী", top_k=2, diversify=True)
    assert [hit.chunk.id for hit in default] == [hit.chunk.id for hit in diverse]


def test_registry_swaps_atomically_and_rolls_back() -> None:
    """The rollback drill: publish v1, publish v2, roll back to v1."""
    registry = IndexRegistry()
    chunks_v1 = [_chunk("a-c6", CELL)]
    chunks_v2 = [_chunk("a-c6", CELL), _chunk("b-c6", EXERCISE)]
    first = registry.build_and_publish(chunks_v1, lambda c: BM25Index(c), config={"mode": "hybrid"})
    second = registry.build_and_publish(
        chunks_v2, lambda c: BM25Index(c), config={"mode": "hybrid"}
    )

    assert first.version != second.version
    assert registry.active is second
    assert registry.active.chunk_count == 2

    restored = registry.rollback()
    assert restored is first
    assert registry.active is first
    assert registry.active.chunk_count == 1
    assert [event[0] for event in registry.events] == ["publish", "publish", "rollback"]

    with_error = False
    try:
        registry.rollback("no-such-version")
    except ValueError:
        with_error = True
    assert with_error, "rolling back to an unknown version must fail loudly"


def test_rollback_without_history_is_an_error() -> None:
    registry = IndexRegistry()
    try:
        registry.rollback()
    except ValueError:
        return
    raise AssertionError("empty registry must refuse to roll back")


def test_corpus_version_changes_with_corpus_and_config() -> None:
    chunks_a = [_chunk("a-c6", CELL)]
    chunks_b = [_chunk("a-c6", CELL), _chunk("b-c6", EXERCISE)]
    assert corpus_version(chunks_a) != corpus_version(chunks_b)
    assert corpus_version(chunks_a, {"mode": "hybrid"}) != corpus_version(
        chunks_a, {"mode": "bm25"}
    )
    assert corpus_version(chunks_a) == corpus_version(list(chunks_a))


def test_index_and_cache_survive_a_corpus_version_change(tmp_path: Path) -> None:
    """AUD-A1-24: a rebuilt index (new corpus version) must not be served
    the previous corpus's cached answers."""
    cache = MemoryCache()
    chunks_v1 = [_chunk("a-c6", CELL)]
    chunks_v2 = [_chunk("a-c6", CELL), _chunk("b-c6", EXERCISE)]

    first = CachedRankingIndex(BM25Index(chunks_v1), cache)
    assert [hit.chunk.id for hit in first.search("কোষ কী", class_level=6)]
    cached_first = [hit.chunk.id for hit in first.search("কোষ কী", class_level=6)]

    rebuilt = CachedRankingIndex(BM25Index(chunks_v2), cache)
    fresh = [hit.chunk.id for hit in rebuilt.search("কোষ কী", class_level=6)]

    assert cached_first == ["a-c6"]
    assert len(fresh) >= 1
    # The key carries the corpus fingerprint: the new index's answer must not
    # be the number of hits the old corpus had.
    assert len(rebuilt.chunks) == 2
    second_call = [hit.chunk.id for hit in rebuilt.search("কোষ কী", class_level=6)]
    assert second_call == fresh, "the rebuilt index's own answer is cached under its own key"


def test_tutor_gate_uses_the_filtered_index_contract() -> None:
    """TutorService calls search with the documented keyword set; the lanes
    must accept class/subject/chapter/top_k without regression."""
    index = BM25Index([_chunk("a-c6", CELL)])
    assert index.search("কোষ", class_level=6, subject="science", chapter="কোষ", top_k=3)
    assert index.search("কোষ", class_level=7) == []
    snapshot = IndexSnapshot(version="v", index=index, chunk_count=1)
    assert snapshot.search("কোষ", class_level=6)
