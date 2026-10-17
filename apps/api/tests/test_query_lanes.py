"""Unit tests for the Bangla ⇄ roman transliteration and the vocabulary
matching structures (spelling lane + Banglish lane + document frequencies)."""

from bangla_gpt_api.retrieval.transliteration import (
    bounded_distance,
    edit_budget,
    similarity,
    to_roman,
)
from bangla_gpt_api.retrieval.vocabulary import CorpusVocabulary

# --- transliteration ----------------------------------------------------------


def test_to_roman_keeps_consonant_clusters_readable() -> None:
    assert to_roman("কোষ") == "kosh"
    assert to_roman("ত্রিকোণমিতি") == "trikonmiti"


def test_to_roman_drops_the_hasanta_marker() -> None:
    # ্ is a cluster marker, not a sound: dropping it lets cluster letters
    # concatenate the way students type them.
    assert "্" not in to_roman("ভগ্নাংশ")
    assert to_roman("ভগ্নাংশ") == "bhgnangsh"


def test_to_roman_transliterates_bengali_digits() -> None:
    assert to_roman("৬ষ্ঠ") == "6shth"


def test_to_roman_passes_code_switched_latin_through() -> None:
    assert to_roman("cell কী") == "cell ki"


def test_similarity_is_edit_normalised() -> None:
    assert similarity("kosh", "kosh") == 1.0
    assert similarity("kosh", "kos") == 0.75  # one deletion on four letters
    # unrelated words score LOW, not zero: bounded Levenshtein over ten
    # characters admits up to two edits, and "kosh"/"trikonmiti" share 6 of
    # them. Callers rely on thresholds (0.6+), not on absolute zero.
    assert similarity("kosh", "trikonmiti") < 0.45


def test_edit_budget_is_length_scaled() -> None:
    assert edit_budget(3) == 1
    assert edit_budget(6) == 2
    assert edit_budget(12) == 2
    assert edit_budget(20) == 3


def test_bounded_distance_gives_up_beyond_the_budget() -> None:
    assert bounded_distance("abcd", "abzz", 2) == 2
    # distance 4 cannot exist with a budget of 2 — bounded means bounded
    assert bounded_distance("abcd", "zzzz", 2) is None


# --- vocabulary: document frequencies + the two match lanes -------------------


def _vocab(df: dict[str, int], n: int = 200) -> CorpusVocabulary:
    return CorpusVocabulary.from_frequencies(df, n)


def test_document_frequency_round_trips() -> None:
    v = _vocab({"কোষ": 40, "ক্লোরোফিল": 3})
    assert v.document_frequency("কোষ") == 40
    assert v.document_frequency("অজানা") == 0
    assert v.total_documents == 200


def test_spelling_lane_repairs_known_misspellings() -> None:
    v = _vocab({"কোষ": 40, "ভগ্নাংশ": 12, "পিথাগোরাসের": 5})
    assert "কোষ" in v.match_spelling("কোশ")
    assert "ভগ্নাংশ" in v.match_spelling("ভগনংশ")
    assert any("পিথাগোরাস" in hit for hit in v.match_spelling("পাইথাগোরাস"))


def test_spelling_lane_ignores_known_terms() -> None:
    # an in-vocabulary term is not a misspelling of anything
    v = _vocab({"কোষ": 40})
    assert v.match_spelling("কোষ") == []


def test_spelling_lane_rejects_meaning_changing_pairs() -> None:
    # হাইপা (colloquial "hypotenuse") vs মাপা ("measure"): same length,
    # edit distance 2, similarity exactly 0.6 — excluded by the
    # first-grapheme rule; abbreviations belong to curated expansion.
    v = _vocab({"মাপা": 20})
    assert "মাপা" not in v.match_spelling("হাইপা")


def test_roman_lane_matches_student_typing() -> None:
    v = _vocab({"কোষ": 40, "ভগ্নাংশ": 12, "ত্রিকোণমিতি": 8})
    assert "কোষ" in v.match_roman("kosh")
    assert "ত্রিকোণমিতি" in v.match_roman("trikonmiti")


def test_roman_lane_vowel_skeleton_recovers_schwa_instability() -> None:
    """ভগ্নাংশ is typed bhagnangsho / bhognangsho / bhagnangsh — the vowels
    refuse one-to-one matching; the consonant frame does not."""
    v = _vocab({"ভগ্নাংশ": 12})
    assert "ভগ্নাংশ" in v.match_roman("bhognangsho")
    assert "ভগ্নাংশ" in v.match_roman("bhagnangsho")


def test_roman_lane_cannot_match_english_instruction_words() -> None:
    """The Banglish lane must stay cosmetic: an instructions-style red-team
    query expands to no curriculum term, so adversarial queries keep
    refusing."""
    v = _vocab({"কোষ": 40, "শ্বসন": 9, "চুম্বক": 6})
    assert v.match_roman("instructions") == []


def test_spelling_lane_ignores_latin_terms() -> None:
    v = _vocab({"kosh": 4})  # a Latin term inside the corpus is not spellable
    assert v.match_spelling("koshh") == []
