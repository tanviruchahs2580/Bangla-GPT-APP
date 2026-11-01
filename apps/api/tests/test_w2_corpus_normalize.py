"""The shared Bangla normalizer and the offset map (F-133/RAG-04).

What these tests pin:

* one normalizer for ingestion and queries: ``retrieval.normalize`` is the
  single definition, ``nctb.normalize.normalize_bangla`` is its ingest form
  (whitespace collapsed) and the tutor's query boundary produces the same
  Unicode form (NFKC + zero-width strip) for identical input;
* the offset map is exact at run granularity: the source slice of every span
  normalizes to the span's text.
"""

from __future__ import annotations

import unicodedata

import pytest

from bangla_gpt_api.nctb.chunking import RawChunk, chunk_pages, highlight_spans
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.nctb.normalize import normalize_bangla
from bangla_gpt_api.retrieval.hybrid import tokenize
from bangla_gpt_api.retrieval.normalize import (
    collapse_whitespace,
    normalize_nfkc,
    normalize_with_offsets,
)
from bangla_gpt_api.services.tutor import normalize_query

#: Inputs that exercise every branch: precomposed/decomposed Bangla, a
#: compatibility ligature, a modifier symbol NFKC expands into a space plus a
#: combining mark, zero-width inserts, NBSP and irregular whitespace.
FIXTURES = [
    "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক।",
    "সালোকসংশ্লেষণ",
    "কো\u200dষ ক\u200dী?",  # ZWJ inside words
    "  one   two\nthree\tfour  ",
    "ﬁle Æsop \u00bd cup",  # NFKC compatibility decompositions
    "Aa\u00a8vq web\u00a8vm",  # Bijoy ASCII: NFKC -> space + U+0308
    "শ্রেণি\u00a0৬ ও ৬ষ্ঠ",  # NBSP and Bengali digits
    "গতিবেগ = দূরত্ব / সময়",
    "ᬒ",  # a script outside the Bangla block, untouched
]


class TestSharedNormalizerEquality:
    """Ingest and query must agree on the Unicode form (the F-133 defect)."""

    def test_query_normalizer_and_shared_normalizer_agree_byte_for_byte(self) -> None:
        for text in FIXTURES:
            assert normalize_nfkc(text) == normalize_query(text), text

    def test_ingest_normalizer_is_the_query_form_plus_whitespace(self) -> None:
        for text in FIXTURES:
            assert normalize_bangla(text) == collapse_whitespace(normalize_query(text)), text

    def test_tokenizer_sees_the_same_tokens_on_both_sides(self) -> None:
        for text in FIXTURES:
            assert tokenize(normalize_bangla(text)) == tokenize(normalize_query(text)), text


class TestOffsetMap:
    def test_text_matches_the_plain_normalizer(self) -> None:
        """Per-cluster NFKC must be byte-identical to whole-string NFKC."""
        for text in FIXTURES:
            assert normalize_with_offsets(text).text == normalize_bangla(text), text

    def test_is_nfkc_stable(self) -> None:
        for text in FIXTURES:
            normalized = normalize_with_offsets(text).text
            assert unicodedata.normalize("NFKC", normalized) == normalized, text

    def test_offsets_are_monotone_and_in_bounds(self) -> None:
        for text in FIXTURES:
            normalized = normalize_with_offsets(text)
            previous = (0, 0)
            for start, end in normalized.offsets:
                assert 0 <= start < end <= len(text), text
                assert (start, end) >= previous, text
                previous = (start, end)
            assert len(normalized.offsets) == len(normalized.text)

    def test_map_span_returns_the_source_of_a_normalized_span(self) -> None:
        text = "মান   নির্ণয়ের\tপদ্ধতি"
        normalized = normalize_with_offsets(text)
        for index, char in enumerate(normalized.text):
            span = normalized.map_span(index, index + 1)
            assert span is not None
            assert normalize_bangla(text[span[0] : span[1]]) == normalize_bangla(char)

    def test_ascii_digits_option_keeps_the_map(self) -> None:
        source = "শ্রেণি ৬"
        normalized = normalize_with_offsets(source, ascii_digits=True)
        assert normalized.text == "শ্রেণি 6"
        assert normalized.map_span(0, len(normalized.text)) == (0, len(source))


class TestChunkSourceSpans:
    def _page(self) -> PageText:
        return PageText(
            7,
            "অধ্যায়: কোষ\nকোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক। "
            + "মাইটোসিস  কোষ বিভাজনের ফলে  সন্ততি কোষ দ্বিগুণ হয়। " * 12,
        )

    def test_every_chunk_run_round_trips_to_its_source(self) -> None:
        page = self._page()
        chunks = chunk_pages([page], source_id="s1")
        assert chunks
        for chunk in chunks:
            cursor = 0
            for span in chunk.source_spans:
                assert (
                    span.text_start == cursor or chunk.text[cursor : span.text_start].strip() == ""
                )
                cursor = span.text_end
                assert span.page == 7
                source = normalize_bangla(page.text[span.page_start : span.page_end])
                own = normalize_bangla(chunk.text[span.text_start : span.text_end])
                assert source == own
            assert spans_cover(chunk)

    def test_original_text_is_the_source_slice(self) -> None:
        chunks = chunk_pages([self._page()], source_id="s1")
        chunk = chunks[0]
        assert chunk.original_text
        assert chunk.original_text in self._page().text

    def test_highlight_spans_map_a_matched_span(self) -> None:
        chunks = chunk_pages([self._page()], source_id="s1")
        chunk = chunks[0]
        start = chunk.text.index("কোষ হলো")
        spans = highlight_spans(chunk, start, start + 8)
        assert spans, "a matched span must map into the source"
        assert spans[0].text_start == 0
        assert normalize_bangla(self._page().text[spans[0].page_start : spans[0].page_end]) != ""

    def test_highlight_of_an_empty_span_is_empty(self) -> None:
        chunk = RawChunk(
            chunk_id="x",
            parent_id=None,
            text="কোষ",
            original_text="কোষ",
            chapter="",
            page_start=1,
            page_end=1,
        )
        assert highlight_spans(chunk, 2, 2) == []


def spans_cover(chunk: RawChunk) -> bool:
    """True when the spans tile the chunk text except for join spaces."""
    cursor = 0
    for span in chunk.source_spans:
        if span.text_start < cursor:
            return False
        if chunk.text[cursor : span.text_start].strip():
            return False
        cursor = span.text_end
    return cursor == len(chunk.text)


def test_spans_cover_a_multi_page_chunk() -> None:
    pages = [
        PageText(1, "অধ্যায়: বল\n" + "বল ও গতি নিয়ে আলোচনা শুরু। " * 20),
        PageText(2, "নিউটনের সূত্র " * 40),
    ]
    chunks = chunk_pages(pages, source_id="s2")
    assert chunks
    assert {chunk.page_start for chunk in chunks} == {1}
    spanning = [chunk for chunk in chunks if chunk.page_end == 2]
    assert spanning, "the fixture must produce a chunk that crosses the page boundary"
    for chunk in spanning:
        assert spans_cover(chunk)


@pytest.mark.parametrize("text", FIXTURES)
def test_normalizer_is_idempotent(text: str) -> None:
    once = normalize_bangla(text)
    assert normalize_bangla(once) == once
