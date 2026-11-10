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
    "SYMBOL_FONT_GLYPHS",
    "ZERO_WIDTH_CHARS",
    "NormalizedText",
    "bangla_char_ratio",
    "de_pua",
    "detect_class_level",
    "detect_class_levels",
    "looks_like_garbage",
    "normalize_bangla",
    "normalize_bangla_with_offsets",
]

#: Symbol/Wingdings private-use glyphs the PDF text layer emits for list
#: markers, and the printable character each one depicts.
#:
#: NBT-002 (audit): the shipped corpus held **2,048 private-use characters
#: across 301 of 852 chunks**, and 56 of them sat *inside* a Bangla word.
#: NCTB prints lists with a symbol font, so pypdf returns the font's
#: private-use slot (``U+F0B7`` is the Wingdings bullet, ``U+F0D8`` the
#: Symbol bullet, ``U+F02D`` the hyphen) rather than the character the glyph
#: draws. ``content_qa`` flags every one as ``pua_char`` — correctly, because
#: a private-use code point is meaningless to a tokenizer and the Bangla-aware
#: pattern ``[A-Za-z0-9\u0980-\u09FF]+`` splits a word around it, so a bullet
#: landing mid-word destroys that word for retrieval.
#:
#: Hence a key choice: every entry is a **one-character-to-one-character**
#: translation, never a deletion. ``SourceSpan`` offsets are computed over the
#: extracted page text and drive source highlighting, so deleting a character
#: would shift every later offset and silently misplace the citation a student
#: clicks. Mapping keeps every span addressing the same position.
SYMBOL_FONT_GLYPHS: dict[int, str] = {
    0xF020: " ",  # Wingdings space -> SPACE
    0xF021: "!",  # Wingdings exclamation -> EXCLAMATION MARK
    0xF02C: ",",  # Wingdings comma -> COMMA
    0xF02D: "-",  # Wingdings hyphen -> HYPHEN-MINUS
    0xF02F: "/",  # Wingdings slash -> SOLIDUS
    0xF038: "8",  # Wingdings digit -> DIGIT EIGHT
    0xF076: "\u25cf",  # Wingdings circle -> BLACK CIRCLE
    0xF0A7: "\u25aa",  # Wingdings small square -> BLACK SMALL SQUARE
    0xF0B2: "\u2022",  # Symbol small bullet -> BULLET
    0xF0B4: "\u2022",  # Symbol bullet variant -> BULLET
    0xF0B7: "\u2022",  # Wingdings bullet -> BULLET
    0xF0D8: "\u2022",  # Symbol bullet -> BULLET
    0xF0FC: "\u2022",  # Wingdings badge glyph -> BULLET
}

#: Any *remaining* private-use character after the explicit map. There is no
#: printable equivalent to recover, so it becomes a space — one character in,
#: one character out, for the offset reason given above — which keeps the
#: surrounding word boundaries instead of gaining a token-splitting code point.
_PUA_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))


def _is_pua(ch: str) -> bool:
    return any(lo <= ord(ch) <= hi for lo, hi in _PUA_RANGES)


def de_pua(text: str) -> str:
    """Replace Symbol/Wingdings private-use glyphs with what they depict.

    Length-preserving by construction and idempotent — both properties are
    load-bearing (see :data:`SYMBOL_FONT_GLYPHS`), and both are asserted.
    """
    if not text or not any(_is_pua(ch) for ch in text):
        return text
    return "".join(SYMBOL_FONT_GLYPHS.get(ord(ch), " ") if _is_pua(ch) else ch for ch in text)


def normalize_bangla(text: str, *, ascii_digits: bool = False) -> str:
    """NFKC-normalize, drop zero-width characters and collapse whitespace.

    Private-use symbol glyphs are resolved first (NBT-002) so the stored text
    and the tokenizer both see the character the page actually prints.
    """
    normalized = collapse_whitespace(normalize_nfkc(de_pua(text)))
    if ascii_digits:
        normalized = normalized.translate(BENGALI_DIGITS)
    return normalized


def normalize_bangla_with_offsets(text: str, *, ascii_digits: bool = False) -> NormalizedText:
    """Like :func:`normalize_bangla`, plus the map back into ``text``.

    The private-use substitution happens on the way *in* rather than on the
    way out (NBT-002). ``de_pua`` is one character for one character, so the
    translated string has the same length and the same indices as ``text`` —
    which is what lets the returned offset map still address the original.
    Doing it afterwards would leave a map that points one character off past
    every replaced glyph, and that map is what places the highlight on the
    sentence a student clicked in the sources panel.
    """
    return normalize_with_offsets(de_pua(text), ascii_digits=ascii_digits)


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
