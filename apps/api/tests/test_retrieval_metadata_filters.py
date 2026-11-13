"""Book/year metadata filters (retrieval engine v2, stage 2).

CurriculumMeta carries book and curriculum_year; the lanes filtered only
class/subject/chapter. The owner's component table names all five. The
sample corpus has one book/year, so the tests use synthetic chunks where a
second book/year is distinguishable.
"""

from __future__ import annotations

from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.retrieval.embedding import HashingEmbedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex


def _chunk(cid: str, text: str, *, book: str, year: int) -> Chunk:
    return Chunk(
        id=cid,
        text=text,
        meta=CurriculumMeta(
            curriculum_year=year,
            class_level=6,
            subject="science",
            book=book,
            source=f"src-{book}-{year}",
            chapter="কোষ",
        ),
    )


def _chunks() -> list[Chunk]:
    return [
        _chunk("old-1", "কোষ জীবের গঠন ও কার্যের ক্ষুদ্রতম একক।", book="Old Book", year=2019),
        _chunk("new-1", "কোষ জীবের গঠন ও কার্যের ক্ষুদ্রতম একক।", book="New Book", year=2026),
    ]


def _settings() -> Settings:
    return Settings(env="test", jwt_secret="test-secret-0123456789abcdef0123456789")


def test_bm25_filters_by_book() -> None:
    index = BM25Index(_chunks())
    hits = index.search("কোষ", book="New Book", top_k=5)
    assert [h.chunk.id for h in hits] == ["new-1"]


def test_bm25_filters_by_year() -> None:
    index = BM25Index(_chunks())
    hits = index.search("কোষ", year=2019, top_k=5)
    assert [h.chunk.id for h in hits] == ["old-1"]


def test_vector_filters_by_book_and_year() -> None:
    index = HybridIndex(_chunks(), HashingEmbedder())
    hits = index.search("কোষ", book="Old Book", year=2026, top_k=5)
    # both filters together match nothing (old book is 2019, new book is 2026)
    assert hits == []


def test_hybrid_book_filter_scopes_both_lanes() -> None:
    index = HybridIndex(_chunks(), HashingEmbedder())
    hits = index.search("কোষ", book="New Book", top_k=5)
    assert [h.chunk.id for h in hits] == ["new-1"]


def test_no_filter_returns_both_class_copies() -> None:
    index = HybridIndex(_chunks(), HashingEmbedder())
    hits = index.search("কোষ", top_k=5)
    assert {h.chunk.id for h in hits} == {"old-1", "new-1"}
