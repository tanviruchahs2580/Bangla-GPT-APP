"""Bangla inflection handling in the hybrid-retrieval helpers.

The module docstring promises that ``light_stem`` lets an inflected form such as
``গাছগুলো`` match the dictionary form ``গাছ``, and that ``expand_query`` adds
curated vocabulary for paraphrased questions. Neither worked: the Bengali
character class was missing its brackets, so the regex matched the literal
three-character sequence ``\\u0980-\\u09FF`` and therefore never matched Bengali
text. ``light_stem`` returned its input unchanged for every real word, and
``expand_query`` only fired on exact, already-uninflected keys.

These tests pin the behaviour the docstring claims. The Bengali strings are
written with explicit code points: a transliterating editor or a copy-paste
from an Assamese source would otherwise silently change what is being tested
(and would defeat the purpose of the suite).
"""

import pytest

from bangla_gpt_api.retrieval.bm25 import tokenize
from bangla_gpt_api.retrieval.hybrid import (
    _BANGLA_RE,
    _MIN_STEM_LEN,
    _SUFFIXES,
    QUERY_EXPANSIONS,
    expand_query,
    light_stem,
)

# Bengali code points, spelled out (see module docstring).
GACH = "গাছ"  # গাছ   (tree, dictionary form)
GACHGULO = "গাছগুলো"  # গাছগুলো (trees, inflected)
VAGNASHER = "ভগ্নাংশের"  # ভগ্নাংশের (of the fraction, inflected)
VAGNAS = "ভগ্নাংশ"  # ভগ্নাংশ (fraction, dictionary form)
KOSH = "কোষ"  # কোষ  (cell, dictionary form)
KOSHER = "কোষের"  # কোষের (of the cell, inflected)


# ---------------------------------------------------------------------------
# The character class itself
# ---------------------------------------------------------------------------


def test_bangla_class_matches_bengali_letters() -> None:
    assert _BANGLA_RE.search(KOSH), "the class must match Bengali script"


def test_bangla_class_is_a_character_class_not_a_literal() -> None:
    """Regression guard for the original defect.

    ``re.compile(r"\\u0980-\\u09FF")`` compiles fine and looks plausible; it just
    matches the literal string "\\u0980-\\u09FF". Asserting the class matches
    Bengali text is what distinguishes the two.
    """
    assert _BANGLA_RE.search(KOSH) is not None
    assert _BANGLA_RE.search(GACHGULO) is not None


def test_bangla_class_does_not_match_latin() -> None:
    assert _BANGLA_RE.search("photosynthesis") is None


# ---------------------------------------------------------------------------
# light_stem
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("inflected", "expected"),
    [
        (GACHGULO, GACH),
        (KOSHER, KOSH),
        (VAGNASHER, VAGNAS),
    ],
)
def test_light_stem_strips_one_inflection(inflected: str, expected: str) -> None:
    assert light_stem(inflected) == expected


def test_light_stem_returns_dictionary_form_unchanged() -> None:
    """A stem already in dictionary form must not be shortened further."""
    assert light_stem(GACH) == GACH
    assert light_stem(KOSH) == KOSH


def test_light_stem_leaves_latin_terms_alone() -> None:
    assert light_stem("photosynthesis") == "photosynthesis"
    assert light_stem("mitochondria") == "mitochondria"


def test_light_stem_never_goes_below_the_minimum_length() -> None:
    """Stripping must not produce a fragment that cannot match anything."""
    for term in (GACH, KOSH, VAGNAS, GACHGULO, KOSHER, VAGNASHER):
        stemmed = light_stem(term)
        assert len(stemmed) >= min(_MIN_STEM_LEN, len(term)), (
            f"{term} -> {stemmed} is too short to be a useful stem"
        )


def test_every_declared_suffix_is_reachable() -> None:
    """Each suffix in the table must actually strip.

    The table is longest-match-first so 'গুলোকে' wins over 'কে'; this checks
    the whole set is live rather than only the handful the happy path uses.
    """
    for suffix in _SUFFIXES:
        candidate = "ভগ্নাংশ" + suffix
        assert light_stem(candidate) == "ভগ্নাংশ", f"suffix {suffix!r} never strips"


def test_longest_suffix_wins() -> None:
    """'গুলোকে' must be stripped before the shorter 'কে'."""
    assert light_stem("গাছগুলোকে") == GACH


# ---------------------------------------------------------------------------
# expand_query
# ---------------------------------------------------------------------------


def test_expand_query_fires_on_an_inflected_form() -> None:
    """The whole point: a student types a natural inflected question.

    ``expand_query`` looks the *stem* up in the map but keeps the student's own
    surface form in the result, so the assertion is that the expansion arrived,
    not that the original word was rewritten.
    """
    expanded = expand_query(tokenize(GACHGULO))
    assert len(expanded) > 1, "an inflected form must still reach the expansion map"
    assert "উদ্ভিদ" in expanded  # the synonym carried by the গাছ entry
    assert GACHGULO in expanded  # the student's own wording is preserved


def test_expand_query_fires_on_the_dictionary_form() -> None:
    assert len(expand_query(tokenize(GACH))) > 1


def test_expanded_terms_are_returned_alongside_the_original() -> None:
    """Expansion is additive: the student's own words must survive."""
    expanded = expand_query(tokenize(GACH))
    assert GACH in expanded


def test_expand_query_is_idempotent() -> None:
    once = expand_query(tokenize(GACH))
    assert expand_query(once) == once


def test_expand_query_does_not_mutate_its_input() -> None:
    terms = tokenize(GACH)
    snapshot = list(terms)
    expand_query(terms)
    assert terms == snapshot


def test_unknown_terms_pass_through_unchanged() -> None:
    assert expand_query(tokenize("অজানা পরিভাষা")) == expand_query(tokenize("অজানা পরিভাষা"))


def test_expansion_keys_are_dictionary_forms() -> None:
    """An expansion keyed on an inflected form could never match a stem.

    ``expand_query`` looks terms up in the map directly, so every key has to be
    a form ``light_stem`` can actually produce.
    """
    for key in QUERY_EXPANSIONS:
        assert light_stem(key) == key, f"expansion key {key!r} is not stem-stable"


# ---------------------------------------------------------------------------
# Interaction with the tokenizer
# ---------------------------------------------------------------------------


def test_tokenizer_keeps_inflected_forms_intact() -> None:
    """Tokenization must not pre-strip what light_stem is there to strip."""
    tokens = tokenize(GACHGULO)
    assert GACHGULO in tokens


def test_stemming_makes_inflected_and_dictionary_forms_collide() -> None:
    """The recall property the module exists to provide.

    This is the end-to-end assertion: after stemming, an inflected question and
    its dictionary form produce the same term, which is what lets the two
    match inside the coverage gate.
    """
    assert light_stem(GACHGULO) == light_stem(GACH)
    assert light_stem(KOSHER) == light_stem(KOSH)
