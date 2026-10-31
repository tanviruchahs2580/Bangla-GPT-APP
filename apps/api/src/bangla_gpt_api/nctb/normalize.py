"""Bangla-safe text normalization for NCTB extracted content.

Keeps ``original_text`` untouched and produces ``normalized_text`` used
for indexing/retrieval. Never destroys mathematical/scientific notation:
normalization is limited to Unicode form, zero-width characters,
whitespace and optional numeral conversion.

The Unicode form is the shared one from ``retrieval.normalize``: NFKC plus
zero-width removal, so the ingested text is the same form the query path
produces (F-133). ``normalize_bangla`` adds the whitespace collapse the
stored chunk text needs; ``normalize_bangla_with_offsets`` additionally
returns the map back into the original string.
"""

from __future__ import annotations

import re

from bangla_gpt_api.retrieval.normalize import (
    BENGALI_DIGITS,
    ZERO_WIDTH_CHARS,
    NormalizedText,
    collapse_whitespace,
    normalize_nfkc,
    normalize_with_offsets,
)

__all__ = [
    "BENGALI_CLASS_WORDS",
    "BENGALI_DIGITS",
    "ZERO_WIDTH_CHARS",
    "NormalizedText",
    "bangla_char_ratio",
    "detect_class_level",
    "detect_class_levels",
    "looks_like_garbage",
    "normalize_bangla",
    "normalize_bangla_with_offsets",
]


def normalize_bangla(text: str, *, ascii_digits: bool = False) -> str:
    """NFKC-normalize, drop zero-width characters and collapse whitespace."""
    normalized = collapse_whitespace(normalize_nfkc(text))
    if ascii_digits:
        normalized = normalized.translate(BENGALI_DIGITS)
    return normalized


def normalize_bangla_with_offsets(text: str, *, ascii_digits: bool = False) -> NormalizedText:
    """Like :func:`normalize_bangla`, plus the map back into ``text``."""
    return normalize_with_offsets(text, ascii_digits=ascii_digits)


def bangla_char_ratio(text: str) -> float:
    """Fraction of alphabetic characters inside the Bangla Unicode block."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    bangla = sum(1 for c in letters if "\u0980" <= c <= "\u09ff")
    return bangla / len(letters)


def looks_like_garbage(text: str) -> bool:
    """Heuristic corruption detector: replacement chars / mojibake ratio."""
    if not text.strip():
        return True
    total = len(text)
    bad = sum(1 for c in text if c == "\ufffd")
    # CID-mapped custom fonts often surface as isolated ASCII punctuation runs
    printable_letters = sum(1 for c in text if c.isalpha())
    if total and bad / total > 0.05:
        return True
    return bool(printable_letters == 0 and any(c.isprintable() for c in text))


BENGALI_CLASS_WORDS = {
    "ষষ্ঠ": 6,
    "সপ্তম": 7,
    "অষ্টম": 8,
    "নবম": 9,
    "দশম": 10,
    "একাদশ": 11,
    "দ্বাদশ": 12,
}

#: Longest ordinal first so "একাদশ" is never read as part of a shorter word.
_ORDINAL = "|".join(sorted(BENGALI_CLASS_WORDS, key=len, reverse=True))

#: Book-level class statements as printed on a cover/title page, including the
#: RANGE forms real NCTB books use: "একাদশ ও দ্বাদশ শ্রেণি", "একাদশ-দ্বাদশ
#: শ্রেণি", "নবম-দশম শ্রেণি", "ষষ্ঠ থেকে অষ্টম শ্রেণি". The ordinals and the
#: word শ্রেণি must sit in one phrase; separate mentions ("ষষ্ঠ শ্রেণি ও সপ্তম
#: শ্রেণি") are not a book-level statement and stay undetected by
#: :func:`detect_class_level`.
_CLASS_RANGE_RES = (
    re.compile(f"({_ORDINAL})\\s*(?:-|–|—|থেকে|to)\\s*({_ORDINAL})\\s*শ্রেণী?"),
    re.compile(f"({_ORDINAL})\\s*(?:ও|,|,|and)\\s*({_ORDINAL})\\s*শ্রেণী?"),
)
_CLASS_SINGLE_RE = re.compile(f"({_ORDINAL})\\s*শ্রেণী?")


def detect_class_levels(text: str, *, scan_chars: int = 16000) -> tuple[int, ...]:
    """Derived class levels a book's *cover statement* declares.

    Returns the covered class set in ascending order — ``(11, 12)`` for a
    combined HSC book whose cover reads "একাদশ ও দ্বাদশ শ্রেণি", ``(6,)`` for
    "ষষ্ঠ শ্রেণি" — and ``()`` when no book-level statement is present, so a
    caller never has to guess. Callers must pass the cover/title text only:
    front-matter policy prose mentions many classes
    ("ষষ্ঠ থেকে অষ্টম শ্রেণির ১৭টি ... নবম ও দশম শ্রেণির ২৭টি") and is not a
    statement about the book itself.
    """
    head = normalize_bangla(text[:scan_chars])
    for pattern in _CLASS_RANGE_RES:
        match = pattern.search(head)
        if match is None:
            continue
        low = BENGALI_CLASS_WORDS.get(match.group(1))
        high = BENGALI_CLASS_WORDS.get(match.group(2))
        if low is None or high is None:
            continue
        if low <= high:
            return tuple(range(low, high + 1))
        return tuple(sorted((low, high)))
    singles = {
        BENGALI_CLASS_WORDS[match.group(1)]
        for match in _CLASS_SINGLE_RE.finditer(head)
        if match.group(1) in BENGALI_CLASS_WORDS
    }
    if len(singles) == 1:
        return (next(iter(singles)),)
    return ()


def detect_class_level(text: str, *, scan_chars: int = 16000) -> int | None:
    """Derive the class level from textbook cover/front-matter wording.

    Returns None when not detectable — callers must NOT guess (master §75).
    The result is derived metadata, not authoritative publication data.
    Multiple distinct class mentions (multi-year compilations) → None.
    """
    head = normalize_bangla(text[:scan_chars])
    found: list[int] = []
    for word, level in BENGALI_CLASS_WORDS.items():
        if f"{word} শ্রেণি" in head or f"{word}শ্রেণি" in head or f"{word} শ্রেণী" in head:
            found.append(level)
    unique = sorted(set(found))
    if len(unique) == 1:
        return unique[0]
    return None  # ambiguous (multi-class compilation) → do not invent
