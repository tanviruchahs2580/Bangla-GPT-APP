"""Property-based tests (hypothesis) for the text pipeline (E-11).

Four components carry the RAG pipeline's text handling and were covered, until
now, only by example-based tests written alongside the code:

* ``nctb.normalize`` -- Bangla-safe normalization of extracted text;
* ``retrieval.hybrid`` -- the tokenizer/stemmer/trigram helpers every
  retrieval lane shares;
* ``nctb.chunking`` -- sentence splitting and sentence-boundary packing;
* ``services.safety.verify_citation`` -- the grounding gate's citation check.

Example tests pin the cases someone thought of. These pin the *invariants* the
rest of the system depends on:

* normalization is idempotent and NFC-stable (index and query must not drift);
* the chunker never loses a word (the 2026-10-18 fix exists because the old
  implementation dropped overflow tails silently);
* "১২৩" and "123" are the same token on both the corpus and the query side
  (digit fold + NFKC);
* the citation check is monotone in evidence -- adding retrieved evidence can
  only make a citation verdict more tolerant, never less.

Every property can fail; each test names the mutation of the code under test
that breaks it, and ``.audit/tmp/e2-mutations.txt`` (evidence ``E-R2-e2-005``)
records scripted mutations executed against them: deleting the digit fold,
returning un-normalized text, truncating oversize pieces and inverting the
citation threshold each turn a specific test here red.

Bengali literals are ``\\uXXXX`` escapes only (repo rule for new files).
"""

from __future__ import annotations

import itertools
import unicodedata
from collections import Counter

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from bangla_gpt_api.nctb.chunking import RawChunk, dedupe_chunks, pack_sentences, split_sentences
from bangla_gpt_api.nctb.normalize import (
    BENGALI_CLASS_WORDS,
    PUA_RANGES,
    ZERO_WIDTH_CHARS,
    bangla_char_ratio,
    detect_class_level,
    in_private_use_area,
    looks_like_garbage,
    normalize_bangla,
    strip_private_use,
)
from bangla_gpt_api.retrieval.hybrid import (
    light_stem,
    tokenize,
    trigram_jaccard,
    trigram_ngrams,
    trigram_similarity,
)
from bangla_gpt_api.services.safety import verify_citation
from factories import BN_SENTENCE

# ── strategies ────────────────────────────────────────────────────────────

#: Bangla consonants only: no combining marks, so a generated word is one
#: tokenizer token and never ends in an inflection the stemmer strips.
CONSONANTS = (
    "\u0995\u0996\u0997\u0998\u0999\u099a\u099b\u099c\u099d\u099e"
    "\u099f\u09a0\u09a1\u09a2\u09a3\u09a4\u09a5\u09a6\u09a7\u09a8"
    "\u09aa\u09ab\u09ac\u09ad\u09ae\u09af\u09b0\u09b2\u09b6\u09b7\u09b8\u09b9"
)
BENGALI_DIGITS = "\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef"
DANDA = "\u0964"

bangla_word = st.text(alphabet=CONSONANTS, min_size=3, max_size=10)
bangla_sentence = st.lists(bangla_word, min_size=1, max_size=6).map(
    lambda words: " ".join(words) + DANDA
)
bangla_letters = st.text(alphabet=CONSONANTS + "\u09c7\u09be\u09bf\u09c1", min_size=1, max_size=40)
any_text = st.text(max_size=120)
pua_char = st.sampled_from([chr(0xE000), chr(0xE123), chr(0xF8FF), chr(0xF0000), chr(0x10FFFD)])
junk_char = st.one_of(pua_char, st.sampled_from(sorted(ZERO_WIDTH_CHARS)), st.just("\ufffd"))
class_words = sorted(BENGALI_CLASS_WORDS)


def props(**overrides):
    """Hypothesis settings shared by this module (no wall-clock deadline)."""
    base = dict(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    base.update(overrides)
    return settings(**base)


# ── normalizer ────────────────────────────────────────────────────────────


@props()
@given(any_text)
def test_normalize_bangla_is_idempotent(text: str) -> None:
    """Re-normalizing must not change the text again (index/query symmetry)."""
    once = normalize_bangla(text)
    assert normalize_bangla(once) == once


@props()
@given(any_text)
def test_normalize_bangla_outputs_nfc_without_invisible_residue(text: str) -> None:
    """Output is NFC and free of zero-width/PUA characters.

    Mutation that breaks it: dropping the ``unicodedata.normalize`` call, the
    zero-width sweep, or the ``strip_private_use`` step.
    """
    out = normalize_bangla(text)
    assert unicodedata.is_normalized("NFC", out)
    assert not any(char in out for char in ZERO_WIDTH_CHARS)
    assert not any(in_private_use_area(char) for char in out)


@props()
@given(any_text)
def test_normalize_bangla_collapses_and_strips_whitespace(text: str) -> None:
    out = normalize_bangla(text)
    assert out == out.strip()
    assert "  " not in out
    assert not any(char in out for char in "\n\r\t")


@props()
@given(st.text(alphabet=CONSONANTS + BENGALI_DIGITS + " ", max_size=60))
def test_normalize_bangla_ascii_digits_converts_every_bengali_digit(text: str) -> None:
    """``ascii_digits=True`` maps the Bengali digits and changes nothing else.

    Mutation that breaks it: deleting the ``str.maketrans`` table or skipping
    the ``translate`` call.
    """
    out = normalize_bangla(text, ascii_digits=True)
    source_digits = sum(1 for char in text if char in BENGALI_DIGITS)
    assert sum(1 for char in out if char.isascii() and char.isdigit()) == source_digits
    assert not any(char in BENGALI_DIGITS for char in out)


@props()
@given(any_text)
def test_strip_private_use_replaces_with_a_space_and_keeps_length(text: str) -> None:
    """PUA glyphs become spaces -- removed, but never glue two words together."""
    out = strip_private_use(text)
    assert len(out) == len(text)
    for original, replaced in zip(text, out, strict=True):
        assert replaced == (" " if in_private_use_area(original) else original)


@props()
@given(st.integers(min_value=0, max_value=0x10FFFF))
def test_in_private_use_area_matches_the_declared_ranges(code_point: int) -> None:
    expected = any(low <= code_point <= high for low, high in PUA_RANGES)
    assert in_private_use_area(chr(code_point)) is expected


@props()
@given(bangla_letters)
def test_bangla_char_ratio_is_one_for_pure_bangla_letters(text: str) -> None:
    assume(any(char.isalpha() for char in text))
    assert bangla_char_ratio(text) == 1.0


@props()
@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=30))
def test_bangla_char_ratio_is_zero_for_latin_letters(text: str) -> None:
    assert bangla_char_ratio(text) == 0.0
    assert bangla_char_ratio("") == 0.0  # no letters at all -> 0.0, never a ZeroDivision


@props()
@given(any_text, st.lists(junk_char, max_size=6))
def test_looks_like_garbage_flags_replacement_heavy_and_empty_text(
    text: str, injected: list[str]
) -> None:
    """More than 5% U+FFFD is corruption; clean alphabetic text never is.

    Mutation that breaks it: changing the 0.05 ratio, dropping the
    ``bad / total`` branch, or returning False for empty input (an empty page
    IS a failed extraction).
    """
    for candidate in (text + "".join(injected), "".join(injected) * 3, text):
        verdict = looks_like_garbage(candidate)
        if not candidate.strip():
            assert verdict is True
            continue
        if candidate.count("\ufffd") / len(candidate) > 0.05:
            assert verdict is True
        if candidate.count("\ufffd") == 0 and any(char.isalpha() for char in candidate):
            assert verdict is False


@props()
@given(st.sampled_from(class_words))
def test_detect_class_level_reads_one_unambiguous_class_word(word: str) -> None:
    """Exactly one class word -> that level.

    Mutation that breaks it: an off-by-one in a ``BENGALI_CLASS_WORDS`` entry
    or a missing ``শ্রেণি`` spelling variant.
    """
    text = f"{word} \u09b6\u09cd\u09b0\u09c7\u09a3\u09bf"  # "<class> shreni"
    assert detect_class_level(text) == BENGALI_CLASS_WORDS[word]
    assert (
        detect_class_level(f"{word}\u09b6\u09cd\u09b0\u09c7\u09a3\u09bf")
        == BENGALI_CLASS_WORDS[word]
    )


@props()
@given(st.sampled_from(class_words), st.sampled_from(class_words))
def test_detect_class_level_refuses_ambiguous_front_matter(left: str, right: str) -> None:
    """Two distinct class mentions -> None (multi-year files must not be guessed).

    Mutation that breaks it: returning the first match instead of None.
    """
    assume(left != right)
    text = (
        f"{left} \u09b6\u09cd\u09b0\u09c7\u09a3\u09bf \u098f\u09ac\u0982 "
        f"{right} \u09b6\u09cd\u09b0\u09c7\u09a3\u09bf"
    )
    assert detect_class_level(text) is None


@props()
@given(any_text)
def test_detect_class_level_returns_none_when_absent(text: str) -> None:
    assume(not any(f"{word} " in text for word in BENGALI_CLASS_WORDS))
    assume(
        not any(
            f"{word}\u09b6\u09cd\u09b0\u09c7\u09a3\u09bf" in text for word in BENGALI_CLASS_WORDS
        )
    )
    assert detect_class_level(text) is None


# ── tokenizer / stemmer ───────────────────────────────────────────────────


@props()
@given(st.text(alphabet="0123456789", min_size=1, max_size=12))
def test_tokenize_folds_bengali_digits_to_ascii(text: str) -> None:
    """ASCII digits and their Bengali spelling are the same token.

    Mutation that breaks it: deleting ``_DIGIT_FOLD`` from the comprehension.
    """
    translated = text.translate(str.maketrans("0123456789", BENGALI_DIGITS))
    assert tokenize(translated) == tokenize(text) == [text]


@props()
@given(any_text)
def test_tokenize_is_nfkc_stable(text: str) -> None:
    """Normalizing twice (NFKC inside ``tokenize``) cannot change the tokens."""
    assert tokenize(unicodedata.normalize("NFKC", text)) == tokenize(text)


@props()
@given(
    st.text(
        alphabet=CONSONANTS + "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ  0123456789"
    )
)
def test_tokenize_folds_ascii_and_bangla_case(text: str) -> None:
    """Upper- and lower-case spellings of the same text are equivalent.

    Deliberately restricted to the product's two scripts: a case-insensitive
    claim over *any* Unicode is false (``"ß".upper() == "SS"``), and the
    tokenizer's contract is ASCII + the Bangla block.
    """
    assert tokenize(text.upper()) == tokenize(text.lower()) == tokenize(text)


@props()
@given(any_text)
def test_tokenize_emits_only_lowercase_alnum_bangla_tokens(text: str) -> None:
    """Every token is a maximal run of ASCII alphanumerics or Bangla codepoints.

    Mutation that breaks it: switching the explicit Bangla range for ``\\w+``
    (which splits graphemes at combining marks) or dropping ``.lower()``.
    """
    tokens = tokenize(text)
    folded = str.maketrans(BENGALI_DIGITS, "0123456789")
    for token in tokens:
        assert token
        assert token == token.lower() == token.translate(folded)
        assert all(
            (char.isascii() and char.isalnum()) or "\u0980" <= char <= "\u09ff" for char in token
        )
    # Round-trip: re-tokenizing the joined tokens is a fixed point.
    assert tokenize(" ".join(tokens)) == tokens


@props()
@given(bangla_word)
def test_light_stem_is_a_prefix_that_respects_the_minimum_length(term: str) -> None:
    """Stemming only removes a suffix and never shortens below ``_MIN_STEM_LEN``.

    Mutation that breaks it: removing the length guard (short terms would be
    reduced to fragments) or returning a rewritten root instead of a prefix.
    """
    stem = light_stem(term)
    assert term.startswith(stem)
    assert len(stem) >= min(3, len(term))
    assert stem == term  # consonant-only words carry no inflectional suffix


@props()
@given(bangla_word)
def test_light_stem_strips_a_known_suffix_at_most_once(term: str) -> None:
    """Appending ``ের`` (the genitive) yields the unsuffixed word back.

    The base must not end in ``দ``: ``দের`` is also a suffix and matches first
    (longest-first order), which the failing case ``কককদ`` + ``ের`` showed
    during this test's development.
    """
    assume(len(term) >= 3 and not term.endswith("\u09a6"))
    assert light_stem(term + "\u09c7\u09b0") == term
    assert light_stem(term) == term


@props()
@given(any_text, any_text)
def test_trigram_similarity_is_symmetric_and_bounded(left: str, right: str) -> None:
    score = trigram_similarity(left, right)
    assert 0.0 <= score <= 1.0
    assert abs(score - trigram_similarity(right, left)) < 1e-12
    assert abs(trigram_jaccard(trigram_ngrams(left), trigram_ngrams(right)) - score) < 1e-12


@props()
@given(bangla_letters)
def test_trigram_similarity_with_itself_is_one_for_long_enough_text(text: str) -> None:
    assume(len("".join(text.split())) >= 3)
    assert trigram_similarity(text, text) == 1.0


# ── chunker ───────────────────────────────────────────────────────────────


def _page():
    return st.lists(bangla_sentence, min_size=1, max_size=12).map(" ".join)


@props()
@given(_page())
def test_pack_sentences_loses_no_word(text: str) -> None:
    """Every input word appears in the output exactly once (overlap=0).

    The pre-2026-10-18 implementation truncated the overflow tail; a mutation
    that replaces the split with a truncation makes this assertion fail.
    """
    pieces = pack_sentences(text, target_words=20, min_words=8, max_words=40, overlap_words=0)
    assert Counter(" ".join(pieces).split()) == Counter(text.split())


@props()
@given(_page(), st.integers(min_value=4, max_value=50))
def test_pack_sentences_respects_max_words(text: str, max_words: int) -> None:
    pieces = pack_sentences(
        text,
        target_words=max(2, max_words // 2),
        min_words=1,
        max_words=max_words,
        overlap_words=0,
    )
    assert pieces
    assert max(len(piece.split(" ")) for piece in pieces) <= max_words


@props()
@given(_page(), st.integers(min_value=1, max_value=4))
def test_pack_sentences_overlap_repeats_the_previous_tail(text: str, overlap: int) -> None:
    """Each piece starts with the previous piece's last ``overlap`` words.

    Mutation that breaks it: ``current[-overlap_words:]`` -> ``current[:overlap_words]``.
    """
    pieces = pack_sentences(text, target_words=20, min_words=8, max_words=40, overlap_words=overlap)
    for previous, following in itertools.pairwise(pieces):
        assert following.split(" ")[:overlap] == previous.split(" ")[-overlap:]


@props()
@given(_page())
def test_split_sentences_keeps_every_word_and_ends_on_a_terminator(text: str) -> None:
    pieces = split_sentences(text)
    assert pieces
    assert all(piece == piece.strip() and piece for piece in pieces)
    assert " ".join(pieces).split() == text.split()
    for piece in pieces[:-1]:
        assert piece[-1] in f"{DANDA}?!"


def _raw_chunk(text: str, index: int) -> RawChunk:
    return RawChunk(
        chunk_id=f"c{index}",
        parent_id="p1",
        text=text,
        original_text=text,
        chapter="\u0985\u09a7\u09cd\u09af\u09be\u09af\u09bc",  # odhyay (NFC form)
        page_start=1,
        page_end=1,
    )


@props()
@given(st.lists(bangla_word, min_size=1, max_size=8))
def test_dedupe_chunks_is_idempotent_and_order_preserving(words: list[str]) -> None:
    """Dedupe keeps first wins, reports what it removed, and is a fixed point.

    Mutation that breaks it: hashing raw text without whitespace normalization,
    or dropping the ``seen`` guard.
    """
    chunks = [_raw_chunk(word, index) for index, word in enumerate(words)]
    unique, removed = dedupe_chunks(chunks)
    assert len(unique) + removed == len(chunks)
    assert len(unique) == len(set(words))
    assert len({chunk.text for chunk in unique}) == len(unique)
    assert [chunk.text for chunk in unique] == list(dict.fromkeys(words))
    again, removed_again = dedupe_chunks(unique)
    assert [chunk.chunk_id for chunk in again] == [chunk.chunk_id for chunk in unique]
    assert removed_again == 0


# ── citation check ────────────────────────────────────────────────────────


@props()
@given(bangla_word)
def test_verify_citation_accepts_an_answer_that_echoes_the_evidence(word: str) -> None:
    """An answer drawn from the evidence always verifies (coverage 1.0)."""
    assert verify_citation(word, f"{word} {BN_SENTENCE}") is True
    assert verify_citation(BN_SENTENCE, BN_SENTENCE) is True


@props()
@given(st.lists(bangla_word, min_size=3, max_size=8, unique=True))
def test_verify_citation_refuses_an_answer_with_no_evidence_overlap(terms: list[str]) -> None:
    """Terms the evidence does not contain push coverage to zero -> refuse.

    Mutation that breaks it: inverting the ``>= 0.25`` comparison, or returning
    True instead of False when coverage is zero.
    """
    answer = " ".join(terms)
    answer_terms = {light_stem(term) for term in tokenize(answer) if len(term) >= 3}
    evidence_terms = {light_stem(term) for term in tokenize(BN_SENTENCE)}
    assume(answer_terms)
    assume(not (answer_terms & evidence_terms))
    assert verify_citation(answer, BN_SENTENCE) is False


@props()
@given(bangla_word)
def test_verify_citation_ignores_terms_shorter_than_three_characters(word: str) -> None:
    """A short answer (every term < 3 characters) is not checkable -> pass.

    Mutation that breaks it: changing the ``len(t) >= 3`` filter to ``> 0``
    (a two-letter answer would then be compared and refused).
    """
    short_answer = word[:2]
    assume(tokenize(short_answer))
    assert verify_citation(short_answer, BN_SENTENCE) is True
    assert verify_citation(short_answer, "") is True


@props()
@given(any_text, st.lists(bangla_word, max_size=5))
def test_verify_citation_is_monotone_in_evidence(answer: str, extra: list[str]) -> None:
    """Adding retrieved evidence never turns a passing citation into a failure.

    Mutation that breaks it: computing coverage over evidence terms instead of
    answer terms, or returning False for an empty answer-term set.
    """
    before = verify_citation(answer, BN_SENTENCE)
    after = verify_citation(answer, BN_SENTENCE + " " + " ".join(extra))
    assert not before or after


@props()
@given(st.lists(bangla_word, min_size=5, max_size=6, unique=True))
def test_verify_citation_threshold_is_a_quarter_of_the_answer_terms(terms: list[str]) -> None:
    """Exactly 1/4 coverage verifies, 1/5 does not: the 0.25 boundary is pinned.

    Mutation that breaks it: ``>= 0.25`` -> ``> 0.25`` (1/4 flips to False) or
    ``>= 0.2`` (1/5 flips to True).
    """
    evidence = terms[0]
    assert verify_citation(" ".join(terms[:4]), evidence) is True  # 1 of 4
    assert verify_citation(" ".join(terms), evidence) is False  # 1 of 5 (or 6)
