"""Bangla-safe text normalization for NCTB extracted content.

Keeps ``original_text`` untouched and produces ``normalized_text`` used
for indexing/retrieval. Never destroys mathematical/scientific notation:
normalization is limited to Unicode form, zero-width characters,
whitespace and optional numeral conversion.
"""

from __future__ import annotations

import unicodedata

ZERO_WIDTH_CHARS = {"\u200b", "\u200c", "\u200d", "\ufeff"}
BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def normalize_bangla(text: str, *, ascii_digits: bool = False) -> str:
    """NFC-normalize, drop zero-width characters and collapse whitespace."""
    normalized = unicodedata.normalize("NFC", text)
    for char in ZERO_WIDTH_CHARS:
        normalized = normalized.replace(char, "")
    normalized = " ".join(normalized.split())
    if ascii_digits:
        normalized = normalized.translate(BENGALI_DIGITS)
    return normalized.strip()


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
    if printable_letters == 0 and any(c.isprintable() for c in text):
        return True
    return False


BENGALI_CLASS_WORDS = {
    "ষষ্ঠ": 6,
    "সপ্তম": 7,
    "অষ্টম": 8,
    "নবম": 9,
    "দশম": 10,
    "একাদশ": 11,
    "দ্বাদশ": 12,
}


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
