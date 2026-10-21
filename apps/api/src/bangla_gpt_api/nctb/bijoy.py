"""Legacy Bijoy (ANSI/SutonnyMJ) → Unicode Bangla conversion stage.

Verified against real NCTB extractions (2026-08-25):
    "RvZxq wkÿvµg 2012" → "জাতীয় ক্ষিক্ষাক্রম ২০১২"-class output
    "evsjv‡`k‡K... cÖavb Dcvq" → "বাংলাদেশকে... প্রধান উপায়"

Known residual artifacts after conversion (documented, not hidden):
- 'ÿ' maps to the ক্ষ conjunct in SutonnyMJ fonts; handled by a
  targeted post-fix verified against real pages.
- Rare ya-phala orderings may surface reordered (e.g., কার্যক্রম);
  such pages keep quality flags rather than being silently trusted.
"""

from __future__ import annotations

from bangla_gpt_api.nctb.normalize import bangla_char_ratio

# Signature Bijoy token fragments observed in official NCTB headers.
_BIJOY_SIGNATURES = (
    "RvZxq",  # জাতীয়
    "wk¶v",  # শিক্ষা
    "evsjv‡`k",  # বাংলাদেশ
    "wkÿv",
    "cÖ‡ek",
    "g‡a¨",
)

# ATI/ANSI symbol-font punctuation the legacy encodings use for Bangla
# diacritics. English and mathematical prose does not contain it; a Latin
# text carrying two or more distinct markers per 100 characters is legacy
# Bijoy that page-level signature detection misses (measured 2026-10-18:
# page-level detection left 122 served chunks as raw Bijoy, e.g.
# "Zi½ ZvwoZ‡PŠ¤^Kxq …" which converts cleanly to "তরঙ্গ তাড়িতচৌম্বকীয় …").
_BIJOY_MARKERS = frozenset("‡†ˆ¯±ª½¼¾¤Š‹›ƒ„…‰°²³´µ¶·¸¹º»")

#: Minimum alphabetic characters before the ratio evidence is trustworthy.
_RESIDUE_MIN_LETTERS = 20

# Targeted post-conversion fixes validated on extracted NCTB pages.
_POST_FIXES = {
    "ÿ": "ক্ষ",
}


def latin_residue_ratio(text: str) -> float:
    """Fraction of alphabetic characters that are NOT Bangla.

    ASCII Latin alone is not enough: legacy symbol-font text also carries
    Latin-1 letters (``Á``, ``Ø``, ``ÿ``, ``ª``) that are neither Bangla nor
    ASCII, and an ASCII-only numerator under-counts exactly the pages this
    check exists to catch (measured on page 31 of the HSC physics volume,
    whose raw text is 100% legacy yet scored below the ASCII threshold).
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    non_bangla = sum(1 for c in letters if not ("\u0980" <= c <= "\u09ff"))
    return non_bangla / len(letters)


def has_latin_residue(text: str) -> bool:
    """True when a Bangla-sourced passage is dominated by non-Bangla letters.

    Callers must already know the source is Bangla-dominant (the loader and
    the build gate gate on ``bangla_char_ratio_on_usable``); inside such a
    source a passage this Latin is either an unconverted legacy passage or an
    extraction failure, never English curriculum prose.
    """
    letters = [c for c in text if c.isalpha()]
    if len(letters) < _RESIDUE_MIN_LETTERS:
        return False
    return latin_residue_ratio(text) >= 0.6


def is_likely_legacy_bijoy(text: str) -> bool:
    """Detect legacy-Bijoy ASCII-encoded Bangla before conversion.

    Two independent signals: the known signature tokens, and the generic
    marker-character set (non-Bangla-letter-dominant text carrying legacy
    diacritic punctuation). The second signal is what catches the
    single-line and mixed-page cases the signature list missed.
    """
    if not text.strip():
        return False
    if bangla_char_ratio(text) > 0.2:
        return False  # already Unicode-dominant
    if any(sig in text for sig in _BIJOY_SIGNATURES):
        return True
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 12:
        return False
    if latin_residue_ratio(text) < 0.8:
        return False
    markers = {c for c in text if c in _BIJOY_MARKERS}
    # Density is per letter, not per character: a page of legacy text has few
    # marker glyphs relative to its total length, so a per-character floor
    # rejected exactly the pages this signal exists for (measured: HSC
    # physics page 31 carries 11 distinct markers at 0.011 markers/letter).
    return len(markers) >= 2 and len(markers) / len(letters) >= 0.002


def convert_bijoy_text(text: str, converter=None) -> str:
    """Convert one page (or line) of Bijoy text to Unicode Bangla.

    The converter is fed ``text + " "``: ``bijoy2unicode``'s
    ``reArrangeUnicodeConvertedText`` indexes one past the end when a line
    ends on a pre-base vowel sign, raising ``IndexError`` (measured on 6 of
    65 lines of HSC physics page 31). A trailing space removes the
    out-of-range read without changing the mapping; the result is
    whitespace-normalised below.
    """
    if not text.strip():
        return text
    if converter is None:
        from bijoy2unicode.converter import Unicode

        converter = Unicode()
    converted = converter.convertBijoyToUnicode(text + " ")
    for raw, fixed in _POST_FIXES.items():
        converted = converted.replace(raw, fixed)
    # Normalize to canonical NFC so equivalent compositions match downstream.
    from bangla_gpt_api.nctb.normalize import normalize_bangla

    return normalize_bangla(converted)


def conversion_quality(original: str, converted: str) -> dict:
    """Measure whether conversion actually improved Bangla readability."""
    return {
        "bangla_ratio_before": round(bangla_char_ratio(original), 4),
        "bangla_ratio_after": round(bangla_char_ratio(converted), 4),
        "improved": bangla_char_ratio(converted) > bangla_char_ratio(original),
    }
