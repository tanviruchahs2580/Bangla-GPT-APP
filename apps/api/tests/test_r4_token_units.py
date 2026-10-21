"""A4-04/A2-03: numeral and unit normalization in the retrieval tokenizer.

The equivalence contract: the SAME text expressed in different scripts or
unit spellings must tokenize identically, because the tokenizer serves both
the indexed corpus and the query -- folding both sides is what makes the
equivalence symmetric:

* A2-03 digit equivalence: Bengali digits fold to ASCII (০,১,২ → 0,1,2);
  pinned in both directions and inside mixed words;
* A4-04 unit equivalence: "৩ km", "৩ কিমি" and "৩ কিলোমিটার" fold to the
  one canonical form the NCTB corpus prints (the full Bangla term);
* the fold is exact-token (never substring), so "am" is not folded via
  "m", and non-unit words are untouched;
* NFKC compatibility variants keep tokenizing identically (U+09DF's
  decomposition is the ADR-0006 documented case).
"""

from __future__ import annotations

from bangla_gpt_api.retrieval.hybrid import tokenize


def test_bengali_digits_fold_to_ascii_both_directions_pinned() -> None:
    # A2-03: the digit equivalence is query/corpus symmetric because the
    # fold lives inside tokenize (both sides run it).
    assert tokenize("৩ কিলোমিটার")[:1] == ["3"]
    assert tokenize("123") == tokenize("১২৩")
    assert tokenize("অধ্যায় ৫") == tokenize("অধ্যায় 5")
    # Bengali digits inside a Bangla word context still fold.
    assert tokenize("১ম শ্রেণি")[0] == "1" or tokenize("১ম শ্রেণি")[0].startswith("1")


def test_unit_aliases_fold_to_one_canonical_form() -> None:
    km_variants = ["3 km", "3 kms", "3 kilometre", "3 kilometer", "3 কিমি", "৩ কিলোমিটার"]
    folded = {tuple(tokenize(v)) for v in km_variants}
    assert len(folded) == 1, f"all kilometre spellings must fold identically: {folded}"
    assert folded.pop() == ("3", "কিলোমিটার")


def test_single_letter_unit_alone_folds_but_words_with_it_do_not() -> None:
    assert tokenize("5 m") == ["5", "মিটার"]
    # exact-token policy: "am" contains "m" but is a word, never folded.
    assert tokenize("am") == ["am"]
    assert tokenize("5 g") == ["5", "গ্রাম"]


def test_common_units_have_measurable_tables() -> None:
    assert tokenize("5 kg") == ["5", "কিলোগ্রাম"]
    assert tokenize("5 কেজি") == ["5", "কিলোগ্রাম"]
    assert tokenize("500 গ্রাম") == ["500", "গ্রাম"]
    assert tokenize("5 cm") == ["5", "সেন্টিমিটার"]
    assert tokenize("5 সেমি") == ["5", "সেন্টিমিটার"]
    assert tokenize("10 ঘন্টা") == tokenize("10 hours") == ["10", "ঘণ্টা"]
    assert tokenize("2 লিটার") == tokenize("2 l") == ["2", "লিটার"]
    assert tokenize("30 min") == tokenize("30 মিনিট") == ["30", "মিনিট"]
    assert tokenize("20 sec") == tokenize("20 সেকেন্ড") == ["20", "সেকেন্ড"]
    assert tokenize("2 মিটার") == ["2", "মিটার"]
    assert tokenize("2 metre") == ["2", "মিটার"]


def test_the_measured_a4_04_example_now_folds() -> None:
    """The residual's own example: "3 km" vs "৩ কিলোমিটার" retrieve as one."""
    assert tokenize("3 km") == tokenize("৩ কিলোমিটার")


def test_nfkc_compatibility_variants_still_tokenize_identically() -> None:
    # U+09DF vs U+09AF+U+09BC (the ADR-0006 documented case).
    assert tokenize("\u09df") == tokenize("\u09af\u09bc")
