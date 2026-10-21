"""A2-05: per-chunk content hashes + cross-source near-duplicate detection.

Pins:

* every chunk a build dedupes carries ``content_hash`` (sha256 of the
  normalized text) — the per-chunk analogue of the manifest's per-document
  checksum, written into the chunk artifacts and the report row;
* :func:`near_duplicate_groups` measures the cross-source duplication the
  audit found un-measured: exact reprints (Jaccard 1.0), near-reprints
  (>= 0.9), transitive groups, same-source pairs and short headings
  excluded by design.
"""

from __future__ import annotations

import hashlib

from bangla_gpt_api.nctb.chunking import (
    RawChunk,
    dedupe_chunks,
    near_duplicate_groups,
)


def _chunk(chunk_id: str, source: str, text: str, page: int = 3) -> RawChunk:
    return RawChunk(
        chunk_id=chunk_id,
        parent_id=None,
        text=text,
        original_text=text,
        chapter="কোষ",
        page_start=page,
        page_end=page,
        section="কোষ বিভাজন",
    )


LONG = (
    "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক। প্রতিটি কোষ কোষঝিল্লি দিয়ে আবৃত থাকে এবং "
    "এর ভেতরে থাকে সাইটোপ্লাজম ও নিউক্লিয়াস। কোষ বিভাজনের মাধ্যমে নতুন কোষ সৃষ্টি হয়, "
    "যা বৃদ্ধি ও মেরামতের মূল নিয়ামক। এই প্রক্রিয়ায় বংশগতির বাহক ডিএনএ প্রতিলিপি হয়। "
    "কোষবিজ্ঞান পাঠে কোষের গঠন, অঙ্গাণু ও কাজগুলো পর্যায়ক্রমে আলোচনা করা হয়েছে।"
)


def test_dedupe_stamps_the_content_hash_on_survivors() -> None:
    chunks = [_chunk("a", "src", LONG), _chunk("b", "src", LONG)]
    unique, removed = dedupe_chunks(chunks)
    assert removed == 1 and len(unique) == 1
    expected = hashlib.sha256(" ".join(LONG.split()).encode("utf-8")).hexdigest()
    assert unique[0].content_hash == expected


def test_near_duplicate_groups_finds_exact_cross_source_reprints() -> None:
    records = [("a-1", "src-a", LONG), ("b-1", "src-b", LONG), ("a-2", "src-a", "অন্য পাঠ " * 60)]
    groups = near_duplicate_groups(records)
    assert groups == [[("src-a", "a-1"), ("src-b", "b-1")]]


def test_same_source_duplicates_are_not_reported() -> None:
    records = [("a-1", "src-a", LONG), ("a-2", "src-a", LONG)]
    assert near_duplicate_groups(records) == []


def test_short_headings_never_pair() -> None:
    records = [("a-1", "src-a", "অনুশীলনী"), ("b-1", "src-b", "অনুশীলনী")]
    assert near_duplicate_groups(records) == []


def test_near_reprint_threshold_is_measurable() -> None:
    # One sentence changed (well under 10% of the text) — still near.
    near = LONG.replace("বৃদ্ধি ও মেরামতের মূল নিয়ামক", "বৃদ্ধি ও মেরামতের প্রধান সূত্র")
    records = [("a-1", "src-a", LONG), ("b-1", "src-b", near)]
    groups = near_duplicate_groups(records, threshold=0.9)
    assert len(groups) == 1 and len(groups[0]) == 2

    # Half the text rewritten — measured as NOT near at 0.9.
    far = LONG[: len(LONG) // 2] + "সম্পূর্ণ ভিন্ন অনুচ্ছেদ " * 20
    records = [("a-1", "src-a", LONG), ("b-1", "src-b", far)]
    assert near_duplicate_groups(records, threshold=0.9) == []


def test_transitive_pairs_land_in_one_group() -> None:
    mid = LONG.replace("মূল নিয়ামক", "প্রধান সূত্র")
    far2 = mid.replace("গঠনগত ও কার্যগত একক", "গাঠনিক ও কার্যগত একক")
    records = [("a-1", "src-a", LONG), ("b-1", "src-b", mid), ("c-1", "src-c", far2)]
    groups = near_duplicate_groups(records)
    assert len(groups) == 1
    assert {m[0] for m in groups[0]} == {"src-a", "src-b", "src-c"}
