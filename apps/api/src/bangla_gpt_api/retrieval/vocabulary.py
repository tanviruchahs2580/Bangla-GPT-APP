"""Corpus vocabulary: the statistics and matching structures built once.

Three retrieval problems answer the same question — *"which corpus terms does
this token refer to?"* — so they share one object, built once at index build:

* **Document frequencies** for the grounding gate's coverage weighting (a term
  that appears in every chunk of the textbook cannot carry the gate).
  Exposed through the :class:`TermStats` structural type instead of a base
  class, so any index whose statistics can answer the two questions qualifies
  without inheriting from anything.
* **Spelling repair** for misspelled Bangla queries (``কোশ`` → ``কোষ``): a
  trigram inverted index over the vocabulary, the classic spell-corrector
  structure. It only runs for tokens that are *not* corpus vocabulary, so an
  ordinary query pays one set-membership test.
* **The Banglish lane** for romanised-Bangla tokens (``kosh`` → ``কোষ``):
  romanised corpus terms, bucketed by length band for a bounded candidate
  scan, with a vowel-skeleton second pass — Banglish spelling is
  vowel-unstable (ভগ্নাংশ is typed bhagnangsho / bhognangsho / bhagnangsh)
  while the consonant sequence is stable.

Built from the tokenised corpus by :meth:`from_frequencies`. Nothing here
mutates after construction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from bangla_gpt_api.retrieval.transliteration import (
    bounded_distance,
    edit_budget,
    similarity,
    to_roman,
)

#: Maximum corpus terms returned per lookup. Expansion is a *recall* aid: a
#: handful of high-similarity candidates is enough, and capping it keeps the
#: worst-case query path independent of vocabulary size.
MAX_MATCHES = 6

#: Vowels of the romanisation. Their removal is the skeleton normalisation
#: used by the Banglish second pass.
_VOWELS = "aeiou"


class TermStats(Protocol):
    """What the grounding gate needs to know about corpus term rarity."""

    @property
    def total_documents(self) -> int: ...

    def document_frequency(self, term: str) -> int: ...


def _skeleton(roman: str) -> str:
    """Vowel-stripped roman form: Banglish spelling is vowel-unstable."""
    return "".join(ch for ch in roman if ch not in _VOWELS)


def _trigrams(term: str) -> set[str]:
    """Character trigrams with boundary markers, for the spelling index.

    Boundary markers make prefix/suffix edits separable: ``কোশ`` and ``কোষ``
    share ``␃কো`` where an unpadded version would compare fragments of
    different positions.
    """
    padded = f"␃{term}␄"
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


class CorpusVocabulary:
    """Vocabulary, spelling index and roman index over one tokenised corpus."""

    def __init__(
        self,
        document_frequency: Mapping[str, int],
        total_documents: int,
        *,
        spelling_fuzzy: bool = True,
        roman_fuzzy: bool = True,
    ) -> None:
        self._total_documents = total_documents
        self._df = dict(document_frequency)
        self._terms = frozenset(self._df)

        # Spelling lane: trigram -> terms. Built only over non-Latin terms —
        # an instructions-style English query shares trigrams with romanised
        # banter far too easily to be trusted here.
        self._trigram_terms: dict[str, list[str]] = {}
        self._roman_buckets: dict[int, list[tuple[str, str]]] = {}
        self._skeleton_buckets: dict[str, list[tuple[str, str]]] = {}
        if spelling_fuzzy:
            for term in self._terms:
                if term.isascii():
                    continue
                for gram in _trigrams(term):
                    self._trigram_terms.setdefault(gram, []).append(term)
        if roman_fuzzy:
            for term in self._terms:
                if term.isascii():
                    continue
                roman = to_roman(term)
                if len(roman) < 2:
                    continue
                self._roman_buckets.setdefault(len(roman), []).append((roman, term))
                self._skeleton_buckets.setdefault(_skeleton(roman), []).append((roman, term))

    @classmethod
    def from_frequencies(
        cls,
        document_frequency: Mapping[str, int],
        total_documents: int,
        **flags: bool,
    ) -> CorpusVocabulary:
        """Build from an already-computed document-frequency map."""
        return cls(document_frequency, total_documents, **flags)

    # --- statistics (the TermStats surface) ---------------------------------

    @property
    def total_documents(self) -> int:
        return self._total_documents

    def document_frequency(self, term: str) -> int:
        return self._df.get(term, 0)

    def term_frequencies(self) -> Mapping[str, int]:
        """The raw frequency map (for callers that aggregate or persist it)."""
        return self._df

    # --- spelling lane -------------------------------------------------------

    def match_spelling(self, term: str, *, min_similarity: float = 0.6) -> list[str]:
        """Corpus terms that look like a misspelling of ``term``.

        ``কোশ`` finds ``কোষ``, ``পাইথাগোরাস`` finds ``পিথাগোরাসের``. Only
        tokens that are not already vocabulary reach this, and the trigram
        threshold matches the grounding gate's fuzzy allowance, so "close
        enough to retrieve" and "close enough to gate" cannot disagree. Two
        constraints keep it a spelling aid rather than a meaning changer:

        * candidates come from the trigram index but are *ranked* by
          edit-normalised similarity — a three-gram word shares at most one
          trigram with its own correction (কোশ/কোষ trigram jaccard 0.2, edit
          similarity 0.67), so ranking on trigrams would never surface it;
        * the first Bangla grapheme must match — misspellings from typing move
          letters inside the word, and হাইপা/মাপা (a meaning change, sim 0.60
          exactly) is the boundary case that forces this rule. Abbreviations
          that do change the root (হাইপা → অতিভুজ) belong to curated expansion,
          not to fuzzy matching.
        """
        if not term or term in self._terms:
            return []
        first = term[0]
        query_grams = _trigrams(term)
        if not query_grams:
            return []
        seen: dict[str, None] = {}
        for gram in query_grams:
            for other in self._trigram_terms.get(gram, ()):
                if other[0] != first:
                    continue
                seen.setdefault(other, None)
        scored: list[tuple[float, str]] = []
        for other in seen:
            score = similarity(term, other)
            if score >= min_similarity:
                scored.append((score, other))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [other for _score, other in scored[:MAX_MATCHES]]

    # --- banglish lane -------------------------------------------------------

    def match_roman(self, token: str) -> list[str]:
        """Bangla corpus terms whose romanisation resembles a Latin token.

        ``kosh`` matches ``কোষ`` (``kosh``); ``trikonmiti`` matches
        ``ত্রিকোণমিতি``. Tolerance comes from :func:`edit_budget` — one edit
        for short tokens, two beyond six characters — and the vowel-skeleton
        second pass absorbs the schwa-vowel instability of Banglish typing by
        Hungarian-matching the consonant frame when the vowels refuse.
        """
        wanted = token.strip().lower()
        if not wanted or not wanted.isascii() or len(wanted) < 2:
            return []
        budget = edit_budget(len(wanted))
        # Fuzzy roman matching starts at three characters: a two-character
        # token ("er") is within one edit of nearly every short roman key
        # and would expand to arbitrary terms ("er" -> বের) with maximum
        # coverage weight. Exact roman keys still match at any length.
        matches: list[tuple[int, str]] = []
        for band, entries in self._roman_buckets.items():
            if abs(band - len(wanted)) > budget:
                continue
            for roman, term in entries:
                distance = bounded_distance(wanted, roman, budget)
                # The roman lane has no Bangla script to anchor on, so it
                # carries a stricter floor than the spelling lane (2/3 of the
                # token vs 3/5): a 5-letter gibberish token ("blorg") is
                # otherwise 2 edits from "alor"/"bler" and would score fake
                # BM25 hit for an out-of-domain query.
                if distance is not None and similarity(wanted, roman) >= 0.65:
                    matches.append((distance, term))
        if len(wanted) < 3:
            seen_exact: dict[str, None] = {}
            roman_key = to_roman(wanted)
            for roman, term in self._roman_buckets.get(len(roman_key), ()):
                if roman == roman_key:
                    seen_exact.setdefault(term, None)
            return list(seen_exact)[:MAX_MATCHES]
        if not matches:
            for roman, term in self._skeleton_buckets.get(_skeleton(wanted), ()):
                distance = bounded_distance(wanted, roman, budget + 1)
                if distance is not None:
                    matches.append((distance + 1, term))
        matches.sort(key=lambda pair: (pair[0], pair[1]))
        seen: dict[str, None] = {}
        for _distance, term in matches:
            seen.setdefault(term, None)
        return list(seen)[:MAX_MATCHES]

    # --- inspection -----------------------------------------------------------

    def vocabulary_size(self) -> int:
        return len(self._terms)


def _trigrams_standalone(term: str) -> set[str]:  # pragma: no cover - parity helper
    return _trigrams(term)


def merged_document_frequency(
    frequency_maps: Iterable[Mapping[str, int]],
) -> dict[str, int]:
    """Merge per-source frequency maps into one (multi-source index builds)."""
    merged: dict[str, int] = {}
    for mapping in frequency_maps:
        for term, df in mapping.items():
            merged[term] = merged.get(term, 0) + df
    return merged
