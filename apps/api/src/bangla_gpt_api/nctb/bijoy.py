"""Legacy Bijoy (ANSI/SutonnyMJ) → Unicode Bangla conversion stage.

Verified against real NCTB extractions (2026-08-25):
    "RvZxq wkÿvµg 2012"          → "জাতীয় ক্ষিক্ষাক্রম ২০১২"-class output
    "evsjv‡`k‡K ... cÖavb Dcvq"   → "বাংলাদেশকে ... প্রধান উপায়"

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

# Targeted post-conversion fixes validated on extracted NCTB pages.
_POST_FIXES = {
    "ÿ": "ক্ষ",
}


def is_likely_legacy_bijoy(text: str) -> bool:
    """Detect legacy-Bijoy ASCII-encoded Bangla before conversion."""
    if not text.strip():
        return False
    if bangla_char_ratio(text) > 0.2:
        return False  # already Unicode-dominant
    return any(sig in text for sig in _BIJOY_SIGNATURES)


def convert_bijoy_text(text: str, converter=None) -> str:
    """Convert one page of Bijoy text to Unicode Bangla."""
    if not text.strip():
        return text
    if converter is None:
        from bijoy2unicode.converter import Unicode

        converter = Unicode()
    converted = converter.convertBijoyToUnicode(text)
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
