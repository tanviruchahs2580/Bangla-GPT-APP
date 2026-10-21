"""A3-01: token-sized chunking (wave-5).

Before the fix, chunk size was measured in whitespace words (220/60/400) with
no tokenizer in the loop, so the served unit could not be compared with the
model's own budget. Now the default is token sizing measured with the
configured ``services.context.TokenCounter`` (the calibrated heuristic upper
bound unless a vendor counter is registered), and the token defaults are
DERIVED from the word defaults (2.7812 tokens/word measured on the served
797-chunk artifact) so the unit change is not a silent size change. Word
sizing remains the documented fallback, selected by passing ``target_words``.

These tests pin the unit arithmetic, the sentence discipline and the
never-split-a-unit guarantee on the tricky pages.
"""

from __future__ import annotations

from bangla_gpt_api.nctb.chunking import (
    MAX_TOKENS,
    MAX_WORDS,
    MIN_TOKENS,
    MIN_WORDS,
    TARGET_TOKENS,
    TARGET_WORDS,
    TOKENS_PER_WORD_MEASURED,
    chunk_pages,
    pack_sentences,
    split_sentences,
)
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.services.context import HeuristicTokenCounter, token_counter

SENTENCE = "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক এবং এটি সব জীবের দেহে পাওয়া যায়।"


def test_token_defaults_are_derived_from_the_word_defaults() -> None:
    """The unit change must not be a silent size change."""
    assert round(TARGET_WORDS * TOKENS_PER_WORD_MEASURED) == TARGET_TOKENS
    assert round(MIN_WORDS * TOKENS_PER_WORD_MEASURED) == MIN_TOKENS
    assert round(MAX_WORDS * TOKENS_PER_WORD_MEASURED) == MAX_TOKENS


def test_default_sizing_measures_tokens_not_words() -> None:
    """220 words of long words measure ~880 tokens: token sizing (the default)
    splits them into several pieces, while the old 220-WORD target keeps them
    as one — the unit is what changed, not an arbitrary new size."""
    sentence = " ".join(["প্রতিষ্ঠানের"] * 20) + "।"
    text = " ".join([sentence] * 11)  # 220 words, ~2420 chars
    token_pieces = pack_sentences(text)  # default: TARGET_TOKENS = 612
    word_pieces = pack_sentences(text, target_words=TARGET_WORDS)
    assert len(token_pieces) >= 2, token_pieces
    assert len(word_pieces) == 1, word_pieces
    assert token_counter().count(token_pieces[0]) > TARGET_WORDS, (
        "the first token-sized piece already carries more words than the old "
        "220-word target allowed in one piece"
    )


def test_the_configured_counter_and_unit_are_reported() -> None:
    stats: dict = {}
    chunks = chunk_pages([PageText(1, SENTENCE * 12)], source_id="s1", stats=stats)
    assert chunks
    assert stats["sizing_unit"] == "tokens"
    assert stats["token_counter"] == token_counter().name
    assert stats["chunk_token_lengths"] == [token_counter().count(chunk.text) for chunk in chunks]
    assert len(stats["chunk_word_lengths"]) == len(chunks)


def test_word_sizing_remains_the_documented_fallback() -> None:
    stats: dict = {}
    chunks = chunk_pages(
        [PageText(1, SENTENCE * 12)], source_id="s1", target_words=TARGET_WORDS, stats=stats
    )
    assert chunks
    assert stats["sizing_unit"] == "words"
    assert all(len(chunk.text.split(" ")) <= MAX_WORDS for chunk in chunks)


def test_token_sizing_still_never_cuts_a_sentence() -> None:
    sentences = [f"{SENTENCE[:-1]}{i}।" for i in range(12)]
    text = " ".join(sentences)
    pieces = pack_sentences(text, target_tokens=120, min_tokens=1)
    assert len(pieces) > 1, "the token target must force a split"
    for piece in pieces:
        for sentence in split_sentences(piece):
            assert sentence in text, f"piece boundary cut a sentence: {sentence!r}"
        assert piece.rstrip().endswith(("।", "?", "!"))


def test_a_custom_counter_is_honoured() -> None:
    """A vendor counter (or a test double) replaces the heuristic measurement:
    at 1 char/token the same text packs into far smaller pieces than at the
    default 2.5 chars/token."""
    counter = HeuristicTokenCounter(chars_per_token=1.0, name="test-1cpt")
    text = " ".join(["ক" * 29 + "।"] * 12)  # 12 sentences x ~30 chars
    custom = pack_sentences(text, target_tokens=60, min_tokens=1, counter=counter)
    default = pack_sentences(text, target_tokens=60, min_tokens=1)
    assert len(custom) > len(default)
    assert all(counter.count(piece) <= 2 * 30 for piece in custom)


def test_a_worked_equation_is_never_split_by_the_token_target() -> None:
    """An equation is one unit: a small token target must not cut it in half."""
    equation = "E = mc² = 3 × 10^8 × 2.5 = 7.5 × 10^16 J = Δp × c²"
    page = PageText(1, SENTENCE * 6 + "\n" + equation + "\n" + SENTENCE * 6)
    chunks = chunk_pages([page], source_id="s1", target_tokens=120, min_tokens=1)
    holding = [chunk.text for chunk in chunks if equation in chunk.text]
    fragments = [chunk.text for chunk in chunks if "E = mc²" in chunk.text]
    assert len(holding) == 1, f"the equation must live in exactly one chunk: {chunks}"
    assert fragments == holding, "no chunk may carry a fragment of the equation"


def test_a_preserved_table_row_is_never_split_by_the_token_target() -> None:
    rows = "\n".join(f"শ্রেণি{i}    বিষয়{i}    পরিমাপ{i}    {i * 11}" for i in range(1, 8))
    chunks = chunk_pages(
        [PageText(1, rows + "\n" + SENTENCE * 8)], source_id="s1", target_tokens=90, min_tokens=1
    )
    table_chunks = [chunk.text for chunk in chunks if " | " in chunk.text]
    assert table_chunks
    for text in table_chunks:
        for line in text.splitlines():
            if " | " in line:
                assert line.count(" | ") == 3, f"row split: {line!r}"


def test_the_word_floor_still_admits_short_word_pages() -> None:
    """60 short words are below MIN_TOKENS but must still stand alone (the
    historical word minimum keeps behaving as before)."""
    text = " ".join(["কবি"] * 70)
    pieces = pack_sentences(text)
    assert pieces == [text]
    # ... while a truly short block still merges into its neighbour
    merged = pack_sentences(f"{text} শেষ।", target_tokens=TARGET_TOKENS)
    assert len(merged) == 1
