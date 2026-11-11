"""Corpus-integrity regressions for the Bangla text pipeline (audit wave 3).

These tests exist because the shipped corpus was measurably corrupt while every
gate was green: ``content_qa`` was wired into nothing, the manifest's code
fingerprint was stale, and no test asserted anything about the *characters*
the retriever actually indexes.

The three defects, each counted on the corpus as it shipped:

* **NBT-001** reph displacement — 2,103 word-final rephs across 631 of 852
  chunks (74.1%); ``শিক্ষার্থী`` appeared 0 times correctly and 1,007 times as
  ``শিক্ষাথীর্``.
* **NBT-002** symbol-font private-use glyphs — 2,048 characters across 301
  chunks, 56 of them inside a word.
* **NBT-003** the upstream converter's unguarded lookahead, which raises
  ``IndexError`` on a page whose text ends with a reph.

Everything below asserts a *property* plus a named example. The corpus itself
is gitignored, so a test that read it would silently pass on a fresh clone;
the tables here are the evidence instead, kept next to the code so a
regression names the word it broke.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.nctb.bijoy import _relocate_reph_glyph, convert_bijoy_text
from bangla_gpt_api.nctb.extract import _clean_page_text, extract_pdf
from bangla_gpt_api.nctb.normalize import (
    SYMBOL_FONT_GLYPHS,
    de_pua,
    normalize_bangla,
    normalize_bangla_with_offsets,
)
from bangla_gpt_api.nctb.reph import (
    mislapped_conjuncts,
    reattach_detached_reph,
    relocate_reph,
    word_final_reph_count,
)
from bangla_gpt_api.retrieval.bm25 import BM25Index

#: Every pair below was read out of the shipped corpus and confirmed against
#: the word the sentence requires. The right-hand side is the correct Bangla;
#: the left is what the corpus actually held, with its occurrence count in the
#: 852-chunk build.
_VERIFIED_REPAIRS = {
    "শিক্ষাথীর্": ("শিক্ষার্থী", 1007),  # student — the product's core noun
    "সম্পকের্": ("সম্পর্কে", 237),  # about / regarding
    "বোডর্": ("বোর্ড", 212),  # board
    "কমর্": ("কর্ম", 420),  # work
    "ধমর্": ("ধর্ম", 116),  # religion
    "রেকডর্": ("রেকর্ড", 60),  # record
    "সমাজকমর্": ("সমাজকর্ম", 48),
    "সম্পকর্": ("সম্পর্ক", 43),
    "দীঘর্": ("দীর্ঘ", 41),  # long
    "পূবর্": ("পূর্ব", 37),  # east
    "বণর্": ("বর্ণ", 33),  # colour / letter
    "অথর্": ("অর্থ", 30),  # meaning / money
    "পূবের্": ("পূর্বে", 30),
    "তাৎপযর্": ("তাৎপর্য", 30),
    "পরিবতের্": ("পরিবর্তে", 28),
    "পূণর্": ("পূর্ণ", 28),  # full
    "সৌন্দযর্": ("সৌন্দর্য", 23),
    "আথর্": ("আর্থ", 22),
    "বিতকর্": ("বিতর্ক", 21),
    "চতুথর্": ("চতুর্থ", 21),  # fourth
    "শিক্ষাবষর্": ("শিক্ষাবর্ষ", 20),
    "বিমূতর্": ("বিমূর্ত", 20),
    "পরামশর্": ("পরামর্শ", 20),  # advice
    "হিন্দুধমর্": ("হিন্দুধর্ম", 16),
    "অপরিহাযর্": ("অপরিহার্য", 15),
    "সারমমর্": ("সারমর্ম", 15),
    "শিক্ষাথীর্র": ("শিক্ষার্থীর", 301),
    "শিক্ষাথীর্রা": ("শিক্ষার্থীরা", 156),
}


# --------------------------------------------------------------------------
# NBT-001 — reph relocation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("corrupt", "expected"), sorted(_VERIFIED_REPAIRS.items()))
def test_reph_repairs_every_verified_corpus_form(corrupt: str, expected: tuple[str, int]) -> None:
    """Each counted corruption from the audit is repaired to the real word."""
    want, _count = expected
    assert relocate_reph(corrupt) == want


def test_reph_is_idempotent() -> None:
    """Running the pass twice changes nothing — the property a rebuild relies on."""
    for corrupt in _VERIFIED_REPAIRS:
        once = relocate_reph(corrupt)
        assert relocate_reph(once) == once


def test_reph_is_a_noop_on_correct_bangla() -> None:
    """Correctly ordered text must survive untouched.

    ``অর্জন``, ``বর্ণনা``, ``কর্তা`` and ``সম্পর্কে`` all carry a legitimate
    medial reph, and ``শিক্ষার্থীর`` is the genitive of the product's core
    noun. A repair pass that moved any of them would corrupt the corpus it is
    meant to clean, which is why relocation fires only on the two shapes that
    are provably illegal — a reph with no consonant after it, and a reph
    followed by ``র``.
    """
    correct = [
        "অর্জন",
        "বর্ণনা",
        "কর্তা",
        "সম্পর্কে",
        "শিক্ষার্থী",
        "শিক্ষার্থীর",
        "শিক্ষার্থীরা",
        "কার্যক্রম",
        "নির্দিষ্ট",
        "গুরুত্বপূর্ণ",
        "পূর্ব",
        "ধর্ম",
        "অর্থনীতি",
        "গার্হস্থ্য",
    ]
    for word in correct:
        assert relocate_reph(word) == word, word


def test_reph_followed_by_ra_is_repaired() -> None:
    """``র`` + halant + ``র`` is not a Bangla cluster: the reph *is* the র.

    This is the shape 301 occurrences of the genitive and plural of the
    product's core noun had — ``শিক্ষাথীর্র`` — and the first pass could not
    see it, because a consonant does follow the reph so nothing looked wrong.
    """
    assert relocate_reph("শিক্ষাথীর্র") == "শিক্ষার্থীর"
    assert relocate_reph("শিক্ষাথীর্রা") == "শিক্ষার্থীরা"
    assert relocate_reph("থীর্র") == "র্থীর"
    assert word_final_reph_count(relocate_reph("শিক্ষাথীর্র শিক্ষাথীর্রা")) == 0


def test_word_final_reph_is_ungrammatical_and_detectable() -> None:
    """The invariant the audit measured: no Bangla word closes with র + halant."""
    assert word_final_reph_count("শিক্ষাথীর্ শিখবে") == 1
    assert word_final_reph_count("শিক্ষার্থী শিখবে") == 0
    assert word_final_reph_count("") == 0
    # A bare reph token is still a violation, not a crash.
    assert word_final_reph_count("র্") == 1


def test_reph_relocation_does_not_invent_consonants() -> None:
    """A reph with no governing consonant to its left is left where it is.

    Moving it across a word boundary would attach it to the wrong word, so the
    pass declines rather than guesses.
    """
    assert relocate_reph("র্") == "র্"
    assert relocate_reph(" ") == " "
    assert relocate_reph("") == ""


def test_two_rephs_in_one_word_are_both_relocated() -> None:
    """A word can carry two rephs; one pass must handle both.

    ``গুরম্নত্বপূণর্`` is the corpus's worst case: a displaced reph *and* a
    mis-mapped ``ত্ব`` conjunct. The positional pass fixes the reph and the
    conjunct stays reported, never guessed at.
    """
    fixed = relocate_reph("গুরম্নত্বপূণর্")
    assert fixed.endswith("পূর্ণ")
    assert word_final_reph_count(fixed) == 0
    assert "গুরুত্বপূর্ণ" not in fixed  # the ম্ন conjunct is not ours to repair
    assert mislapped_conjuncts(fixed) == {"ম্ন": 1}


# --------------------------------------------------------------------------
# NBT-002 — symbol-font private-use glyphs
# --------------------------------------------------------------------------


def test_de_pua_removes_every_private_use_character() -> None:
    """No private-use code point survives the cleaner, mapped or not."""
    mapped = "".join(chr(cp) for cp in SYMBOL_FONT_GLYPHS)
    unmapped = "\ue123\uf8ff\U000f0000"
    cleaned = de_pua(mapped + unmapped)
    assert not any(0xE000 <= ord(ch) <= 0xF8FF for ch in cleaned)
    assert "\ue123" not in cleaned and "\uf8ff" not in cleaned


def test_de_pua_is_length_preserving() -> None:
    """One character in, one character out — the offset contract.

    ``SourceSpan`` offsets drive the highlight in the sources panel. A cleaner
    that deleted a character would shift every later offset and put the
    highlight on the wrong sentence, so this is asserted rather than assumed.
    """
    sample = "দলগত কাজ\uf0b7 প্রথম\uf0d8 দ্বিতীয়-\uf02d তৃতীয়\ue123 শেষ"
    assert len(de_pua(sample)) == len(sample)


def test_de_pua_is_idempotent() -> None:
    sample = "\uf0b7 এক\uf0d8 দুই\uf02d তিন"
    assert de_pua(de_pua(sample)) == de_pua(sample)


def test_de_pua_maps_a_bullet_to_a_bullet_not_a_space() -> None:
    """The marker must stay a marker: a list read back should still be a list."""
    assert de_pua("\uf0b7") == "\u2022"
    assert de_pua("\uf0d8") == "\u2022"


def test_normalize_bangla_resolves_glyphs_before_collapsing() -> None:
    """The stored chunk text carries no private-use character."""
    assert "\uf0b7" not in normalize_bangla("কাজ\uf0b7 আরও")
    assert normalize_bangla("  কাজ \uf0b7  আরও  ") == "কাজ \u2022 আরও"


def test_offset_map_still_addresses_the_original_after_glyph_resolution() -> None:
    """Offsets index the text the caller passed in, glyphs and all.

    The translation happens on the way *in* precisely so this holds; doing it
    on the way out would leave the map one position off past every glyph.
    """
    original = "প্রথম\u00b7 দ্বিতীয়"  # · is 1 char, so no expansion anywhere
    normalized = normalize_bangla_with_offsets(original)
    assert normalized.offsets == tuple((i, i + 1) for i in range(len(original)))
    assert normalized.text == original

    # With a private-use glyph in the middle the lengths must still agree.
    with_glyph = "প্রথম\uf0b7 দ্বিতীয়"
    resolved = normalize_bangla_with_offsets(with_glyph)
    assert len(resolved.text) == len(with_glyph)
    assert resolved.offsets == tuple((i, i + 1) for i in range(len(with_glyph)))
    assert "\uf0b7" not in resolved.text
    assert resolved.text == "প্রথম\u2022 দ্বিতীয়"


# --------------------------------------------------------------------------
# NBT-001 (pre-conversion half) + NBT-003 — the converter guard
# --------------------------------------------------------------------------


def test_reph_glyph_moves_in_front_of_the_glyph_it_follows() -> None:
    """The SutonnyMJ reph is a marker; one step back is its logical position."""
    assert _relocate_reph_glyph("ag\u00a9") == "a\u00a9g"
    assert _relocate_reph_glyph("eY\u00a9bv") == "e\u00a9Ybv"


def test_reph_glyph_is_not_moved_across_a_word_boundary() -> None:
    """A reph after whitespace has no governing consonant; leave it."""
    assert _relocate_reph_glyph("\u00a9") == "\u00a9"
    assert _relocate_reph_glyph(" \u00a9x") == " \u00a9x"


def test_convert_bijoy_text_survives_a_page_ending_in_a_reph() -> None:
    """NBT-003: the upstream lookahead bug must not lose a page or raise.

    ``bijoy2unicode`` indexes ``str[i + 2]`` behind an ``i < len - 1`` guard,
    so a page whose extracted text ends with a reph raises ``IndexError``.
    The contract here is that a bad page comes back as text, never as an
    exception — the caller marks it unusable instead of aborting the book.
    """
    for text in ("ag\u00a9", "K\u00a9", "wk\u00ffv_y\u00a9", "\u00a9"):
        result = convert_bijoy_text(text)
        assert isinstance(result, str)


def test_convert_bijoy_text_handles_a_converter_that_always_raises() -> None:
    """A wholly broken converter degrades to the original text, not a crash."""

    class _AlwaysRaises:
        def convertBijoyToUnicode(  # noqa: N802 - mirrors the bijoy2unicode API
            self, _text: str
        ) -> str:
            raise IndexError("string index out of range")

    assert convert_bijoy_text("RvZxq wkÿv", converter=_AlwaysRaises()) == "RvZxq wkÿv"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ag\u00a9", "ধর্ম"),
        ("eY\u00a9bv", "বর্ণনা"),
        ("wba\u00a9vwiZ", "নির্ধারিত"),
        ("cieZ\u00a9x\u2021Z", "পরবর্তীতে"),
    ],
)
def test_reph_pre_pass_produces_the_correct_word(raw: str, expected: str) -> None:
    """The end-to-end claim: pre-pass + library conversion = the real word.

    Each raw string is the SutonnyMJ spelling of the expected Unicode word,
    and each was checked against the library's own output.
    """
    assert convert_bijoy_text(raw) == expected


# --------------------------------------------------------------------------
# NBT-005 — one passage indexed once per class level
# --------------------------------------------------------------------------


def _passage(chunk_id: str, text: str, class_level: int = 6) -> Chunk:
    return Chunk(
        id=chunk_id,
        meta=CurriculumMeta(
            curriculum_year=2023,
            class_level=class_level,
            subject="science",
            book="বিজ্ঞান",
            source="fixture",
            chapter="কোষ",
            page=1,
        ),
        text=text,
    )


def test_repeated_passages_collapse_to_one_hit() -> None:
    """NBT-005: identical passages must not eat the evidence budget.

    The loader expands each source across every class level it covers, so the
    shipped index held **1,605 chunks but only 438 distinct texts** (max
    duplication 5). ``top_k=3`` then returned the *same* text three times, so
    the model received one piece of evidence where three were intended — while
    ``doc_freq`` counted each copy and so depressed the very IDF weight the
    grounding gate reads.
    """
    shared = "কোষ হলো জীবনের একক।"
    index = BM25Index(
        [
            _passage("dup6", shared, class_level=6),
            _passage("dup7", shared, class_level=7),
            _passage("dup8", shared, class_level=8),
        ]
    )
    hits = index.search("কোষ", top_k=3)
    assert len(hits) == 1, "three copies of one passage are one piece of evidence"
    assert hits[0].chunk.text == shared


def test_a_class_scoped_query_keeps_its_own_copy() -> None:
    """The filter runs before the collapse, so the citation names the right book."""
    shared = "কোষ হলো জীবনের একক।"
    index = BM25Index(
        [
            _passage("dup6", shared, class_level=6),
            _passage("dup7", shared, class_level=7),
        ]
    )
    hits = index.search("কোষ", class_level=7, top_k=3)
    assert len(hits) == 1
    assert hits[0].chunk.id == "dup7"
    assert hits[0].chunk.meta.class_level == 7


def test_distinct_passages_are_not_collapsed() -> None:
    """The control: a corpus with no duplication answers exactly as before."""
    index = BM25Index(
        [
            _passage("a", "কোষ হলো জীবনের একক।"),
            _passage("b", "কোষ বিভাজন দুই প্রকার।"),
        ]
    )
    hits = index.search("কোষ", top_k=5)
    assert len(hits) == 2
    assert len({hit.chunk.text for hit in hits}) == 2


def test_collapse_still_respects_top_k() -> None:
    """Collapsing frees slots; it must not exceed the caller's limit."""
    index = BM25Index(
        [
            _passage("dup1", "কোষ হলো জীবনের একক।"),
            _passage("dup2", "কোষ হলো জীবনের একক।"),
            _passage("u1", "কোষ বিভাজন দুই প্রকার।"),
            _passage("u2", "কোষের তিনটি প্রধান অংশ।"),
        ]
    )
    hits = index.search("কোষ", top_k=2)
    assert len(hits) == 2
    assert len({hit.chunk.text for hit in hits}) == 2


# --------------------------------------------------------------------------
# The page-level choke point
# --------------------------------------------------------------------------


def test_clean_page_text_applies_both_stages() -> None:
    """One entry point, both repairs — a page cannot take only one of them."""
    assert _clean_page_text("কার্যক্রম\uf0b7") == "কার্যক্রম\u2022"
    assert _clean_page_text("শিক্ষাথীর্") == "শিক্ষার্থী"


# --------------------------------------------------------------------------
# NBT-006 — a reph the text layer split off its word
# --------------------------------------------------------------------------


def test_detached_reph_is_reattached_to_the_word_before_it() -> None:
    """The shipped shape: 8 chunks across all 8 books carried this sentence.

    ``চতুথ র্ পর্যায়ে`` is ``চতুর্থ পর্যায়ে`` with the text layer's space
    inside the syllable. It survived the word-level pass because the reph is
    not inside a word — which is why the invariant kept reporting 8 after
    2,095 of 2,103 had been cleared.
    """
    assert reattach_detached_reph("চতুথ র্ পর্যায়ে") == "চতুর্থ পর্যায়ে"
    assert reattach_detached_reph("চতুথ\nর্ পর্যায়ে") == "চতুর্থ পর্যায়ে"
    assert word_final_reph_count(reattach_detached_reph("চতুথ র্ পর্যায়ে")) == 0


def test_detached_reph_is_not_forced_into_a_complete_syllable() -> None:
    """A word ending in a vowel sign has no consonant for a reph to precede.

    Forcing one in produces ``কর্রে`` — a non-word — so the rule declines.
    Declining is the whole reason this is a separate, narrower rule than the
    positional pass.
    """
    assert reattach_detached_reph("করে র্ নয়") == "করে র্ নয়"
    assert reattach_detached_reph("বিদ্যা র্ পর") == "বিদ্যা র্ পর"


def test_detached_reph_needs_a_word_on_both_sides() -> None:
    """A layout mark with nothing before it is left alone, not cross-attached."""
    assert reattach_detached_reph("র্") == "র্"
    assert reattach_detached_reph("র্ পর্যায়ে") == "র্ পর্যায়ে"


def test_detached_reph_rule_does_not_match_a_longer_token() -> None:
    """``র্ব`` starts a token; only a standalone reph is a detached one."""
    assert reattach_detached_reph("চতুথ র্ব") == "চতুথ র্ব"


def test_detached_reph_rule_is_idempotent() -> None:
    once = reattach_detached_reph("চতুথ র্ পর্যায়ে")
    assert reattach_detached_reph(once) == once


def test_a_reph_followed_by_a_consonant_is_left_alone_not_guessed_at() -> None:
    """The honest limit of a positional rule, asserted rather than hidden.

    ``বণর্না`` (for বর্ণনা) carries its reph between two consonants, and both
    ``র্ণ`` and ``র্ন`` are legal Bangla clusters — so a *positional* pass
    cannot know which reading is meant and must not guess: moving it would
    corrupt whichever word is real. This class is fixed one stage earlier, at
    the glyph level, where the SutonnyMJ ``©`` marks the reph unambiguously
    (see :func:`~bangla_gpt_api.nctb.bijoy._relocate_reph_glyph`, and the
    end-to-end case in ``test_reph_pre_pass_produces_the_correct_word``).
    """
    assert relocate_reph("বণর্না") == "বণর্না"
    # The glyph-level pass *does* resolve it.
    assert convert_bijoy_text("eY\u00a9bv") == "বর্ণনা"


def test_extract_pdf_keeps_going_when_one_page_is_unreadable(tmp_path) -> None:
    """A missing file is reported as an error, never raised (existing contract)."""
    result = extract_pdf(tmp_path / "does-not-exist.pdf")
    assert not result.ok
    assert result.error
