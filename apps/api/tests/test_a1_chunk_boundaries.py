"""AUD-A1-09 / A3-02: chunk boundaries respect sentences, sizes stay bounded.

Demonstrated before the fix (audit E-A1-006): a 300-word / 10-sentence page
split 1/1 at word 220 — the second sentence of the page was cut in half,
because ``flush`` counted words and ignored ``।`` / ``?`` / ``!``. These
tests pin the sentence-aware packing, the overlap option used by the
chunk-size ablation, and the two structural guarantees the old code broke:
no text is silently truncated, and a numbered curriculum heading is a
section boundary only when the current block can stand alone.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from bangla_gpt_api.nctb.chunking import (
    MAX_WORDS,
    MIN_WORDS,
    TARGET_WORDS,
    RawChunk,
    chunk_pages,
    dedupe_chunks,
    pack_sentences,
    split_sentences,
)
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.nctb.normalize import normalize_bangla

SENTENCE = "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক এবং এটি সব জীবের দেহে পাওয়া যায়।"


def test_split_sentences_keeps_danda_question_and_exclamation() -> None:
    assert split_sentences("কোষ কী? এটা একটি কোষ। ঠিক আছে! শেষ।") == [
        "কোষ কী?",
        "এটা একটি কোষ।",
        "ঠিক আছে!",
        "শেষ।",
    ]
    # ASCII periods do not split: "M.Sc." and abbreviations are not sentences
    assert split_sentences("He passed M.Sc. in 2012 from Dhaka.") == [
        "He passed M.Sc. in 2012 from Dhaka."
    ]


def test_pack_never_cuts_a_sentence_at_the_target_boundary() -> None:
    sentences = [f"{SENTENCE[:-1]}{i}।" for i in range(10)]  # 10 distinct sentences
    text = " ".join(sentences)
    pieces = pack_sentences(text, target_words=20, min_words=1, max_words=MAX_WORDS)
    assert len(pieces) > 1, "target must actually force a split"
    for piece in pieces:
        for sentence in split_sentences(piece):
            assert sentence in text, f"piece boundary cut a sentence: {sentence!r}"


def test_a_long_page_splits_between_sentences_not_mid_sentence() -> None:
    page = PageText(1, " ".join([SENTENCE] * 20))  # ~260 words, 20 sentences
    chunks = chunk_pages([page], source_id="s1", target_words=TARGET_WORDS)
    assert len(chunks) >= 2
    assert " ".join(c.text for c in chunks) == normalize_bangla(page.text), (
        "every word of the page must survive chunking, in order"
    )
    for chunk in chunks:
        assert chunk.text.rstrip().endswith(("।", "?", "!")), (
            f"chunk must end at a sentence boundary: {chunk.text[-40:]!r}"
        )


def test_overlap_repeats_the_tail_of_the_previous_piece() -> None:
    text = " ".join([SENTENCE] * 8)
    with_overlap = pack_sentences(text, target_words=30, min_words=1, overlap_words=5)
    without = pack_sentences(text, target_words=30, min_words=1, overlap_words=0)
    assert len(with_overlap) > 1
    assert with_overlap[1].startswith(" ".join(without[0].split(" ")[-5:]))


def test_oversize_merge_is_split_not_truncated() -> None:
    """The old tail-merge could exceed MAX_WORDS and then dropped the tail."""
    long_sentence = " ".join(["কোষ"] * (MAX_WORDS - 10)) + "।"
    tail = SENTENCE
    pieces = pack_sentences(
        f"{long_sentence} {tail}",
        target_words=MAX_WORDS - 20,
        min_words=MIN_WORDS,
        max_words=MAX_WORDS,
    )
    joined = " ".join(pieces)
    assert tail[:-1] in joined, "the tail sentence must not be truncated away"
    assert all(len(piece.split(" ")) <= MAX_WORDS for piece in pieces)


def test_short_block_is_merged_forward_not_dropped() -> None:
    pages = [
        PageText(1, "সংক্ষিপ্ত।"),  # 1 word: below MIN_WORDS
        PageText(2, " ".join([SENTENCE] * 10)),
    ]
    chunks = chunk_pages(pages, source_id="s1")
    assert "সংক্ষিপ্ত" in " ".join(c.text for c in chunks)
    assert chunks[0].page_start == 1, "merged block keeps its page provenance"


def test_numbered_heading_does_not_fragment_a_numbered_list() -> None:
    """Exercise questions are numbered; a fresh chunk per question would fall
    below MIN_WORDS and lose the answers."""
    digits = "০১২৩৪৫৬৭৮৯"
    lines = [
        f"{digits[i]}। কোষ সম্পর্কে সংক্ষেপে লিখ। বিস্তারিত ব্যাখ্যা দাও যাতে বোঝা যায়।" for i in range(1, 8)
    ]
    page = PageText(1, "অনুশীলনী\n" + "\n".join(lines))
    chunks = chunk_pages([page], source_id="s1")
    assert len(chunks) == 1, f"expected one exercise chunk, got {len(chunks)}"
    assert "৭।" in chunks[0].text


def test_numbered_heading_starts_a_section_when_the_block_is_full() -> None:
    body = " ".join([SENTENCE] * 10)
    page = PageText(1, f"{body}\n৫.২ পরিমাপ ও একক\n{body}")
    chunks = chunk_pages([page], source_id="s1")
    assert len(chunks) >= 2
    assert any(chunk.section.startswith("৫.২") for chunk in chunks), (
        f"numbered curriculum heading must be recorded as a section: {[c.section for c in chunks]}"
    )


def test_section_marker_is_recorded_on_the_chunk() -> None:
    page = PageText(1, f"অনুশীলনী\n{SENTENCE} " * 6)
    chunks = chunk_pages([page], source_id="s1")
    assert chunks and chunks[0].section == "অনুশীলনী"


def test_chunk_word_lengths_histogram_is_reported() -> None:
    stats: dict = {}
    chunks = chunk_pages([PageText(1, " ".join([SENTENCE] * 10))], source_id="s1", stats=stats)
    assert stats["chunk_word_lengths"] == [len(chunk.text.split(" ")) for chunk in chunks]
    assert "short_blocks_merged" in stats


def test_typed_metadata_survives_the_artifact_roundtrip() -> None:
    chunk = RawChunk(
        chunk_id="a",
        parent_id=None,
        text="x",
        original_text="x",
        chapter="",
        page_start=1,
        page_end=2,
        section="অনুশীলনী",
    )
    assert asdict(chunk)["section"] == "অনুশীলনী"


@pytest.mark.parametrize("target", [120, 220, 320])
def test_pack_is_deterministic_for_every_ablation_config(target: int) -> None:
    text = " ".join([SENTENCE] * 12)
    first = pack_sentences(text, target_words=target, min_words=MIN_WORDS)
    second = pack_sentences(text, target_words=target, min_words=MIN_WORDS)
    assert first == second


def test_dedupe_ignores_the_new_section_field() -> None:
    """Dedupe is content-based; a section label must not defeat it."""
    chunk = RawChunk(
        chunk_id="a",
        parent_id=None,
        text=SENTENCE * 3,
        original_text=SENTENCE * 3,
        chapter="",
        page_start=1,
        page_end=1,
    )
    renamed = RawChunk(
        chunk_id="b",
        parent_id=None,
        text=SENTENCE * 3,
        original_text=SENTENCE * 3,
        chapter="",
        page_start=1,
        page_end=1,
        section="অনুশীলনী",
    )
    unique, removed = dedupe_chunks([chunk, renamed])
    assert removed == 1 and len(unique) == 1
