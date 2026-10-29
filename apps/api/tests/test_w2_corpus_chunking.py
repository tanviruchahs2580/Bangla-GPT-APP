"""Chunk size budgets are counted in production tokens (RAG-05/F-134).

The defect: the structural comments claimed a word budget nobody had measured
against the tokenizer the index uses, so the real cost of a chunk was unknown
and the constants were unjustified. These tests pin the unit (production
tokens), the bounds, and that the budget constants really drive the split.
"""

from __future__ import annotations

from bangla_gpt_api.nctb.chunking import (
    MAX_TOKENS,
    MIN_TOKENS,
    SIZE_UNIT,
    TARGET_TOKENS,
    chunk_pages,
)
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.retrieval.hybrid import tokenize

SENTENCE = "সালোকসংশ্লেষণ উদ্ভিদের পাতায় খাদ্য তৈরি করে এবং অক্সিজেন ছড়িয়ে দেয়। "


def _page(sentences: int = 60) -> PageText:
    return PageText(1, SENTENCE * sentences)


def _sizes(chunks) -> list[int]:
    return [len(tokenize(chunk.text)) for chunk in chunks]


def test_budgets_are_declared_in_tokens() -> None:
    assert SIZE_UNIT == "tokens"
    assert 0 < MIN_TOKENS < TARGET_TOKENS < MAX_TOKENS


def test_chunk_sizes_respect_the_token_bounds() -> None:
    chunks = chunk_pages([_page()], source_id="s1")
    sizes = _sizes(chunks)
    assert chunks and len(chunks) > 1, "a 60-sentence page must split"
    assert min(sizes) >= MIN_TOKENS, sizes
    assert max(sizes) <= MAX_TOKENS, sizes


def test_target_token_budget_drives_the_number_of_chunks() -> None:
    page = _page()
    small = chunk_pages([page], source_id="s1", target_tokens=80, min_tokens=20)
    large = chunk_pages([page], source_id="s1", target_tokens=220)
    assert len(small) > len(large)
    assert max(_sizes(small)) <= MAX_TOKENS


def test_words_and_tokens_are_not_the_same_unit() -> None:
    # "3.5" is one whitespace field and two tokens; a word budget measures a
    # different quantity than the index pays for.
    page = PageText(1, ("গতিবেগ 3.5 মিটার প্রতি সেকেন্ডে পরিবর্তিত হয়। " * 30))
    chunks = chunk_pages([page], source_id="s1", target_tokens=120)
    assert chunks
    for chunk in chunks:
        words = len(chunk.text.split())
        tokens = len(tokenize(chunk.text))
        assert tokens >= words
        assert tokens <= MAX_TOKENS


def test_oversize_single_block_is_capped_not_dropped() -> None:
    # one enormous line: the cap trims it, and the first piece still exists
    huge = PageText(1, "কোষ " * 900)
    chunks = chunk_pages([huge], source_id="s1")
    assert chunks
    assert min(_sizes(chunks)) >= MIN_TOKENS
    assert max(_sizes(chunks)) <= MAX_TOKENS


def test_thin_fragments_are_dropped() -> None:
    assert chunk_pages([PageText(1, "কোষ। ")], source_id="s1") == []
