"""Candidate-pool deduplication (retrieval engine v2, stage 3).

The real corpus expands one section into per-class copies and — without the
ingest-time dedupe flag — the same text can occupy several candidate slots:
the reranker then pays for identical texts and RRF spreads their rank mass.
The pool contract under test:

* candidates whose NORMALIZED indexable text is identical AND whose
  ``meta.source`` matches collapse onto the best fused rank;
* same text under a DIFFERENT source stays (source-aware identity);
* the collapse happens BEFORE the reranker, so it pays once per distinct
  text, and the surviving candidate keeps the best fused rank.
"""

from __future__ import annotations

from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.embedding import HashingEmbedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex


def _settings() -> Settings:
    return Settings(env="test", jwt_secret="test-secret-0123456789abcdef0123456789")


def _chunk(cid: str, text: str, *, source: str, section: str = "কোষ") -> Chunk:
    return Chunk(
        id=cid,
        text=text,
        meta=CurriculumMeta(
            curriculum_year=2026,
            class_level=6,
            subject="science",
            book="NCTB Science 6",
            source=source,
            chapter="কোষ",
            section=section,
        ),
    )


def _index() -> HybridIndex:
    # Two candidates carry IDENTICAL text from the SAME source under
    # different chunk ids (the duplication shape the real corpus produces);
    # a third is the same text from a DIFFERENT source (source-aware
    # identity keeps it); a fourth is distinct text.
    chunks = [
        _chunk("dup-a", "কোষ জীবের গঠন ও কার্যের ক্ষুদ্রতম একক।" * 3, source="book-a"),
        _chunk("dup-b", "কোষ জীবের গঠন ও কার্যের ক্ষুদ্রতম একক।" * 3, source="book-a"),
        _chunk("other-src", "কোষ জীবের গঠন ও কার্যের ক্ষুদ্রতম একক।" * 3, source="book-b"),
        _chunk("distinct", "সালোকসংশ্লেষণ হলো খাদ্য তৈরির প্রক্রিয়া।" * 3, source="book-a"),
    ]
    return HybridIndex(chunks, HashingEmbedder())


def test_identical_text_same_source_collapses_in_the_pool() -> None:
    index = _index()
    hits = index.search("কোষ জীবের গঠন", top_k=10)
    ids = [h.chunk.id for h in hits]
    # dup-a and dup-b are the same evidence from the same source: one slot
    assert ("dup-a" in ids and "dup-b" not in ids) or ("dup-b" in ids and "dup-a" not in ids)


def test_same_text_different_source_survives() -> None:
    index = _index()
    hits = index.search("কোষ জীবের গঠন", top_k=10)
    # source-aware identity: book-a's copy and book-b's copy are both kept
    assert {h.chunk.meta.source for h in hits} >= {"book-a", "book-b"}


def test_distinct_text_is_never_dropped() -> None:
    index = _index()
    hits = index.search("সালোকসংশ্লেষণ খাদ্য তৈরির প্রক্রিয়া", top_k=10)
    assert any(h.chunk.id == "distinct" for h in hits)
