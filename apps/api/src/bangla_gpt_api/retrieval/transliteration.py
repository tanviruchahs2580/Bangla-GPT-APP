"""Bangla ⇄ romanised-Bangla transliteration, for code-switched queries.

Bangladeshi students overwhelmingly type subject words in Latin script
("kosh ki", "bhitore ki thake"), a surface form this pipeline previously had
no answer for: the lexical index is Bangla-only, so every Banglish question
abstained. Passing that query through a *grapheme* transliteration and
matching it against romanised corpus vocabulary is the standard lexical
remedy for code-switched retrieval — no model, no network, fully
deterministic.

Design notes an implementer needs:

* The table is ordered longest-match-first and handles vowel signs, the
  hasanta (conjunct marker) and the two ro-letters that mobile keyboards
  conflate. ``to_roman`` emits no implicit vowel: ``কোষ`` → ``kosh``. An
  implied "a" would have made every token one characters longer and split
  the vocabulary across two spellings for no matching benefit — match
  tolerance comes from edit distance, not from guessing vowels.
* ``similar`` is bounded Levenshtein with a length-scaled budget (1 for short
  tokens, 2 beyond six characters) — tight enough that unrelated English
  words stay unmatched, loose enough for one dropped conjunct or a swapped
  s-variant (``কোশ`` vs ``কোষ`` romanise identically anyway).
"""

from __future__ import annotations

# Longest-match-first: multi-character graphemes must be consumed before the
# letters they contain ("খ" kh before "ক" k), or every conjunct decomposes.
#
# The hasanta (্, conjunct marker) is deliberately absent: it only marks
# cluster membership, so dropping it lets cluster letters concatenate the way
# students type them -- ত্রিকোণমিতি -> "trikonmiti", not "t্rikonmiti".
_GRAPHEME_TO_ROMAN: tuple[tuple[str, str], ...] = (
    # hasanta + the vowel carriers that precede forms students type
    ("্", ""),
    # vowels (independent forms first)
    ("ঐ", "oi"),
    ("ঔ", "ow"),
    ("আ", "a"),
    ("ঈ", "i"),
    ("ঊ", "u"),
    ("এ", "e"),
    ("অ", "o"),
    ("ও", "o"),
    ("ই", "i"),
    ("উ", "u"),
    # vowel signs
    ("ৈ", "oi"),
    ("ৌ", "ow"),
    ("ো", "o"),
    ("্য", "y"),
    ("ূ", "u"),
    ("ৃ", "ri"),
    ("ী", "i"),
    ("ে", "e"),
    ("া", "a"),
    ("ি", "i"),
    ("ু", "u"),
    # aspirated and conjunct consonants
    ("ক্ষ", "kh"),
    ("ন্ড", "nd"),
    ("ঞ্জ", "nj"),
    ("ঙ্গ", "ng"),
    ("ক্ক", "k"),
    ("ত্থ", "tth"),
    ("দ্ধ", "ddh"),
    ("ন্ত", "nt"),
    ("স্থ", "stho"),
    ("ষ্ণ", "shn"),
    ("ম্প", "mp"),
    ("জ্ঞ", "j"),
    ("ছ", "chh"),
    ("ক্হ", "kh"),
    ("ঝ", "jh"),
    ("ঞ", "n"),
    ("ঠ", "th"),
    ("ঢ", "dh"),
    ("খ", "kh"),
    ("ঘ", "gh"),
    ("ঙ", "ng"),
    ("চ", "ch"),
    ("জ", "j"),
    ("ট", "t"),
    ("ড", "d"),
    ("ণ", "n"),
    ("ত", "t"),
    ("থ", "th"),
    ("দ", "d"),
    ("ধ", "dh"),
    ("ন", "n"),
    ("প", "p"),
    ("ফ", "f"),
    ("ব", "b"),
    ("ভ", "bh"),
    ("ম", "m"),
    ("য", "j"),
    ("র", "r"),
    ("ল", "l"),
    ("শ", "sh"),
    ("ষ", "sh"),
    ("স", "s"),
    ("হ", "h"),
    ("ক", "k"),
    ("গ", "g"),
    ("ড়", "r"),
    ("ঢ়", "rh"),
    ("য়", "y"),
    ("ৎ", "t"),
    ("ং", "ng"),
    ("ঃ", "h"),
    ("ঁ", ""),
    # Bengali digits — questions number things ("২টি প্রক্রিয়া")
    ("০", "0"),
    ("১", "1"),
    ("২", "2"),
    ("৩", "3"),
    ("৪", "4"),
    ("৫", "5"),
    ("৬", "6"),
    ("৭", "7"),
    ("৮", "8"),
    ("৯", "9"),
)


def to_roman(text: str) -> str:
    """Transliterate Bangla text to a lowercase roman key.

    Non-Bangla characters pass through unchanged (digits, Latin fragments of a
    code-mixed query), so ``to_roman("cell কী")`` is ``"cell ki"``.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        for bangla, roman in _GRAPHEME_TO_ROMAN:
            if text.startswith(bangla, i):
                out.append(roman)
                i += len(bangla)
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out).lower()


def roman_initial(text: str) -> str:
    """First roman letter of the transliteration, for bucketing."""
    roman = to_roman(text)
    return roman[0] if roman else ""


def edit_budget(length: int) -> int:
    """Length-scaled tolerance: one edit for short tokens, two beyond six.

    Tight on purpose. Banglish tokens differ from their corpus form by a
    dropped conjunct or a swapped s-variant — one edit. Two edits buys mobile
    keyboard slips on longer tokens; three would admit unrelated English
    words (``instructions`` vs a romanised Bangla term) into the expansion,
    which is how a spelling aid becomes a grounding hazard.
    """
    if length <= 4:
        return 1
    if length <= 6:
        return 2
    return 2 if length <= 12 else 3


def bounded_distance(a: str, b: str, budget: int) -> int | None:
    """Levenshtein distance, or ``None`` once it provably exceeds ``budget``.

    The bound is the performance contract of the Banglish lane: the
    dictionary lookup buckets candidates first, then each candidate costs
    at most one short row of dynamic programming that stops at a row minimum
    greater than the budget.
    """
    if abs(len(a) - len(b)) > budget:
        return None
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        row_min = i
        for pos, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            value = min(previous[pos] + 1, current[pos - 1] + 1, previous[pos - 1] + cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > budget:
            return None
        previous = current
    distance = previous[-1]
    return distance if distance <= budget else None


def similarity(a: str, b: str) -> float:
    """``1 - distance/max(len)`` in [0, 1]; identical strings score 1."""
    longer = max(len(a), len(b))
    if longer == 0:
        return 1.0
    distance = bounded_distance(a, b, longer)
    if distance is None:
        return 0.0
    return round(1.0 - (distance / longer), 4)
