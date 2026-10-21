"""Bangla-safe text normalization for NCTB extracted content.

Keeps ``original_text`` untouched and produces ``normalized_text`` used
for indexing/retrieval. Never destroys mathematical/scientific notation:
normalization is limited to Unicode form, zero-width characters,
private-use glyph residue, whitespace and optional numeral conversion.
"""

from __future__ import annotations

import unicodedata

ZERO_WIDTH_CHARS = {"\u200b", "\u200c", "\u200d", "\ufeff"}
BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Private-use ranges. The PDF text layer of several NCTB books encodes
# decorative symbol-font glyphs (bullets, list markers) as these code
# points; they render as tofu boxes and carry no textual meaning.
PUA_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))


def in_private_use_area(char: str) -> bool:
    """True when the character is a Unicode private-use code point."""
    code = ord(char)
    return any(low <= code <= high for low, high in PUA_RANGES)


def strip_private_use(text: str) -> str:
    """Replace private-use glyphs with a space.

    A space — not deletion — keeps neighbouring words from being glued
    together. content QA flags any surviving private-use character as
    ``pua_char``, so this is the repair step for that verdict.
    """
    return "".join(" " if in_private_use_area(char) else char for char in text)


def normalize_bangla(text: str, *, ascii_digits: bool = False) -> str:
    """NFC-normalize, drop zero-width chars and PUA residue, collapse space."""
    normalized = unicodedata.normalize("NFC", text)
    for char in ZERO_WIDTH_CHARS:
        normalized = normalized.replace(char, "")
    normalized = strip_private_use(normalized)
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
