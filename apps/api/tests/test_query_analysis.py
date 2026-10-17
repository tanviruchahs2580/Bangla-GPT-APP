"""Unit tests for the query-analysis layer (stop-words, framing, weights).

The regression these lock in was measured on the live deployment: the
grounding gate counted "কোথায়"/"ঘটে"/"এবং" as must-cover terms and refused
"সালোকসংশ্লেষণ কী এবং কোথায় ঘটে?" — a question about a section that exists
in the served corpus — at coverage 0.40.
"""

from bangla_gpt_api.retrieval.hybrid import light_stem
from bangla_gpt_api.retrieval.query_analysis import (
    content_terms,
    coverage_weights,
    english_gloss_terms,
    is_framing_term,
    is_stop_word,
    weighted_coverage,
)


def _weights(terms: tuple[str, ...], df: dict[str, int], n: int = 100) -> dict[str, float]:
    return coverage_weights(terms, {t: df.get(t, 0) for t in terms}, n)


def test_function_words_are_stop_words_in_every_script() -> None:
    for term in ("এবং", "কী", "কোথায়", "ki", "kothay", "and", "what"):
        assert is_stop_word(term), term


def test_content_terms_drop_framing_and_function_words() -> None:
    # Everything except the curriculum concept is scaffolding: the question
    # particle, the instruction pair, the class framing.
    assert content_terms("ভগ্নাংশ কী? explain করো") == ("ভগ্নাংশ",)
    assert content_terms("৬ষ্ঠ শ্রেণির ভগ্নাংশ কী?") == ("ভগ্নাংশ",)


def test_content_terms_keep_concept_vocabulary() -> None:
    # The terms that name the question's subject survive: they are what the
    # gate must demand evidence for.
    assert content_terms("ইউক্লিডের পঞ্চম স্বতঃসিদ্ধ ব্যাখ্যা কর") == (
        "ইউক্লিড",
        "পঞ্চম",
        "স্বতঃসিদ্ধ",
    )


def test_generic_content_words_are_not_stop_words() -> None:
    """The stop list is curated by inflection family, not frequency: on the
    78-chunk sample corpus "কোষ" is among the most frequent tokens in its
    book, and it must never become a stop-word."""
    assert not is_stop_word("কোষ")
    assert not is_stop_word("ভগ্নাংশ")
    assert not is_framing_term("কোষ")


def test_network_or_curriculum_terms_gloss_to_bangla() -> None:
    assert "কোষ" in english_gloss_terms("cell")
    assert english_gloss_terms("Cell") == english_gloss_terms("cell")  # case-folded
    # an unmapped token expands to nothing — no invented coverage
    assert english_gloss_terms("quantumchromodynamics") == ()


def test_idf_weights_rank_rare_terms_above_ubiquitous_ones() -> None:
    terms = ("সালোকসংশ্লেষণ", "এবং")
    df = {"সালোকসংশ্লেষণ": 2, "এবং": 100}
    w = _weights(terms, df, n=2508)
    assert w["সালোকসংশ্লেষণ"] > w["এবং"]


def test_uncovered_moderate_term_cannot_veto_a_high_idf_concept() -> None:
    """The measured false refusal, restated on the terms that survive the
    analysis: সালোকসংশ্লেষণ (df 2, the concept the question names) is
    covered; ঘটে (df 40, a verb the evidence need not repeat) is not. The
    weighted coverage must still clear the 0.5 gate."""
    terms = ("সালোকসংশ্লেষণ", "ঘটে")
    w = _weights(terms, {"সালোকসংশ্লেষণ": 2, "ঘটে": 40}, n=2508)
    assert weighted_coverage(terms, ["সালোকসংশ্লেষণ"], w) >= 0.5


def test_uncovered_concept_terms_cannot_pass_coverage() -> None:
    """The other half of the honesty contract: an out-of-corpus concept word
    keeps maximum weight, so its absence refuses the question."""
    terms = ("ইউক্লিডের", "পঞ্চম", "স্বতঃসিদ্ধ", "ব্যাখ্যা")
    w = _weights(terms, {"পঞ্চম": 40, "ব্যাখ্যা": 30}, n=2508)  # ইউক্লিড/স্বতঃসিদ্ধ df=0
    coverage = weighted_coverage(terms, ["পঞ্চম", "ব্যাখ্যা"], w)
    assert coverage < 0.5


def test_light_stem_strips_only_length_safe_suffixes() -> None:
    assert light_stem("ভগ্নাংশটা") == "ভগ্নাংশ"
    assert light_stem("কোষের") == "কোষ"
    # never below the minimum stem length
    assert len(light_stem("কীটা")) >= 3


def test_numeric_grade_tokens_are_framing_not_content() -> None:
    assert content_terms("৬ষ্ঠ শ্রেণির ভগ্নাংশ কী?") == ("ভগ্নাংশ",)
    # ক্লাস/8/এর are class framing; "science" is the lesson being asked about.
    assert content_terms("ক্লাস 8 এর science") == ("science",)
