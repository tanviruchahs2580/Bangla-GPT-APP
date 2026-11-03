"""RAG-001: chunk versioning, duplicate enforcement and freshness anchors.

- Identical passages (reprints/overlapping pages) are deduped at build time.
- Every build stamps content_version + built_at so staleness is answerable.
- qa_chunks reports the duplicate rate alongside text-quality flags.
"""

from bangla_gpt_api.nctb.chunking import RawChunk, dedupe_chunks
from bangla_gpt_api.nctb.content_qa import qa_chunks


def _chunk(text: str, cid: str) -> RawChunk:
    return RawChunk(
        chunk_id=cid,
        parent_id=None,
        text=text,
        original_text=text,
        chapter="c",
        page_start=1,
        page_end=1,
    )


def test_dedupe_removes_identical_passages_first_wins() -> None:
    chunks = [
        _chunk("কোষ জীবের গঠন একক " * 20, "a"),
        _chunk("কোষ জীবের গঠন একক " * 20, "b"),
        _chunk("সালোকসংশ্লেষণ উদ্ভিদের খাদ্য তৈরি " * 20, "c"),
    ]
    unique, removed = dedupe_chunks(chunks)
    assert removed == 1
    assert [c.chunk_id for c in unique] == ["a", "c"]


def test_dedupe_ignores_whitespace_differences() -> None:
    chunks = [_chunk("কোষ  জীবের\nগঠন একক " * 20, "a"), _chunk("কোষ জীবের গঠন একক " * 20, "b")]
    unique, removed = dedupe_chunks(chunks)
    assert removed == 1
    assert len(unique) == 1


def test_dedupe_empty_is_stable() -> None:
    unique, removed = dedupe_chunks([])
    assert unique == [] and removed == 0


def test_qa_reports_duplicate_rate() -> None:
    rows = [
        {"chunk_id": "a", "text": "কোষ জীবের গঠন একক " * 20},
        {"chunk_id": "b", "text": "কোষ জীবের গঠন একক " * 20},
        {"chunk_id": "c", "text": "সালোকসংশ্লেষণ উদ্ভিদের খাদ্য তৈরি " * 20},
    ]
    report = qa_chunks(rows)
    assert report.total_chunks == 3
    assert report.duplicate_chunks == 1
    assert report.duplicate_ratio == round(1 / 3, 4)
    assert report.to_dict()["duplicate_chunks"] == 1


def test_qa_clean_corpus_has_no_duplicates() -> None:
    rows = [{"chunk_id": str(i), "text": f"অনন্য অনুচ্ছেদ সংখ্যা {i} " * 20} for i in range(5)]
    report = qa_chunks(rows)
    assert report.duplicate_chunks == 0
    assert report.duplicate_ratio == 0.0
