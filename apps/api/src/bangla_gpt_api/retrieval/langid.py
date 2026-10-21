"""Script/language detection for tutor queries (AUD-A1-19).

The audit found that mixed-script input was handled implicitly by the
tokenizer's character classes: nothing in the repo could answer "is this
query Bangla, Banglish (Latin-script Bangla) or English?" — which is what a
metric per query family needs, and what a Banglish subset requires. This
module makes the implicit explicit and is used by the evaluation harness to
label family A/B/D queries; it does not change retrieval behaviour.

Banglish is *not* detected by vocabulary (a romanised Bangla word and an
English word are both Latin letters); it is detected by the Unicode script
mix of the query — a query whose letters are Latin while its curriculum
terms resolve through the romanisation lane. The caller supplies that second
signal: :func:`classify_query` takes the roman-lane matches the retriever
already computed.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise

BANGLA_RANGE = ("\u0980", "\u09ff")
BENGALI_DIGITS = set("০১২৩৪৫৬৭৮৯")
#: Latin-script curriculum words a student types for English-medium content.
ENGLISH_TERMS = frozenset({"cell", "physics", "chemistry", "biology", "energy", "force"})


def script_of(text: str) -> str:
    """Coarse script class of a text: bangla / latin / mixed / other / none.

    Digits (ASCII or Bengali) do not decide the script; they are numerals in
    every one of these languages.
    """
    bangla = latin = 0
    for char in text:
        if char.isdigit() or char in BENGALI_DIGITS:
            continue
        if BANGLA_RANGE[0] <= char <= BANGLA_RANGE[1]:
            bangla += 1
        elif char.isalpha() and char.isascii():
            latin += 1
    if bangla and latin:
        return "mixed"
    if bangla:
        return "bangla"
    if latin:
        return "latin"
    return "other" if any(char.isalpha() for char in text) else "none"


def is_banglish(text: str, *, roman_matches: Iterable[str] = ()) -> bool:
    """True for Latin-script Bangla: Latin letters with Bangla phonetic hits.

    ``roman_matches`` carries the corpus terms the retriever's romanisation
    lane resolved for this query (``CorpusVocabulary.match_roman``); at least
    one hit is required, so plain English questions ("what is a cell?") are
    not relabelled as Banglish.
    """
    if script_of(text) != "latin":
        return False
    return any(term.strip() for term in roman_matches)


def classify_query(text: str, *, roman_matches: Iterable[str] = ()) -> str:
    """Lane label used by the evaluation report and the request logs.

    Returns one of ``bangla``, ``banglish``, ``english``, ``mixed``,
    ``other``/``none``.
    """
    script = script_of(text)
    if script == "bangla":
        return "bangla"
    if script == "mixed":
        return "mixed"
    if script == "latin":
        if is_banglish(text, roman_matches=roman_matches):
            return "banglish"
        words = {word.lower().strip("?!.,") for word in text.split()}
        if words & ENGLISH_TERMS:
            return "english"
        return "banglish" if _looks_romanised(text) else "english"
    return "other" if script == "other" else "none"


def _looks_romanised(text: str) -> bool:
    """Phonetic-shape heuristic for Latin input with no corpus hit.

    Romanised Bangla avoids consonant clusters standard English uses
    ("bhognangsho", "kosh", "salokossholeshon"): a long token with no
    dictionary-ish cluster of three consonants is treated as romanised.
    """
    for word in text.lower().split():
        letters = [char for char in word if char.isalpha()]
        if len(letters) < 4:
            continue
        cluster = 1
        for previous, current in pairwise(letters):
            if previous not in "aeiou" and current not in "aeiou":
                cluster += 1
                if cluster >= 3:
                    return False
            else:
                cluster = 1
    return True


__all__ = ["classify_query", "is_banglish", "script_of"]
