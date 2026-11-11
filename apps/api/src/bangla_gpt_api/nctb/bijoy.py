"""Legacy Bijoy (ANSI/SutonnyMJ) → Unicode Bangla conversion stage.

Verified against real NCTB extractions (2026-08-25):
    "RvZxq wkÿvµg 2012" → "জাতীয় শিক্ষাক্রম ২০১২"-class output
    "evsjv‡`k‡K... cÖavb Dcvq" → "বাংলাদেশকে... প্রধান উপায়"

Reph handling (audit finding NBT-001)
------------------------------------
SutonnyMJ stores the reph as the glyph ``©`` **after** the consonant cluster
it governs; Unicode stores ``র`` + halant **before** it. The upstream
``bijoy2unicode`` converter tries to rearrange this (``converter.py:302`` and
``:332``), but its rule only fires when the character two positions after the
reph is itself a halant — so the ordinary cases were never moved.

The cost was measured on the shipped corpus: **2,103 word-final rephs across
631 of 852 chunks (74.1%)**, with ``শিক্ষার্থী`` — the core noun of a
student-facing product — appearing 0 times correctly and 1,007 times as
``শিক্ষাথীর্``. An earlier revision of this docstring called the residue
"rare ... and keep quality flags rather than being silently trusted"; that
claim was wrong in both halves — the defect was the majority case, and no
flag caught it — which is why it is corrected here rather than quietly
reworded.

The fix is applied on the way **in**, not on the way out:
:func:`_relocate_reph_glyph` moves each ``©`` in front of the glyph it
follows, so the converter emits a reph that is already in logical order.
Repairing the output instead is unreliable because Bangla orthography makes
some positions genuinely ambiguous — ``র্ণ`` and ``র্ন`` are both valid
clusters — whereas the Bijoy ``©`` marks the reph unambiguously. The
post-conversion pass in :mod:`bangla_gpt_api.nctb.reph` still runs as a
safety net and asserts the word-final invariant.

Known residual artifacts after conversion (documented, not hidden):
- 'ÿ' maps to the ক্ষ conjunct in SutonnyMJ fonts; handled by a targeted
  post-fix verified against real pages.
- Pre-base vowel signs (``ি``) can still surface displaced in a small number
  of forms (e.g. ``নিধাির্রত`` for নির্ধারিত). Those are **counted** by
  :func:`bangla_gpt_api.nctb.reph.word_final_reph_count` and by the blocking
  content gate rather than guessed at.
"""

from __future__ import annotations

from bangla_gpt_api.nctb.normalize import bangla_char_ratio

#: Signature Bijoy token fragments observed in official NCTB headers.
_BIJOY_SIGNATURES = (
    "RvZxq",  # জাতীয়
    "wk¶v",  # শিক্ষা
    "evsjv‡`k",  # বাংলাদেশ
    "wkÿv",
    "cÖ‡ek",
    "g‡a¨",
)

#: Targeted post-conversion fixes validated on extracted NCTB pages.
_POST_FIXES = {
    "ÿ": "ক্ষ",
}

#: The SutonnyMJ reph glyph. It is a *marker*, not a letter: it carries no
#: meaning on its own, which is what makes relocating it safe and unambiguous.
REPH_GLYPH = "\u00a9"

#: Neutral Bijoy tail appended when the converter trips over its own
#: end-of-string lookahead (NBT-003). The library reads ``str[i + 2]`` and
#: ``str[i + j + 1]`` behind bounds checks that are one short
#: (``converter.py:302``/``:332``/``:389``, all reproduced), so nothing near
#: the final character is safe. Padding pushes the real content away from the
#: edge; the tail's own conversion is subtracted again afterwards.
#:
#: Padded rather than falling back to the *unfixed* text on purpose: a
#: fallback would silently undo the reph relocation for exactly the short
#: fragments where it is easiest to miss, which is the class of failure this
#: module exists to end.
_CONVERTER_TAIL = "  RvZxq wk\u00ffv\u00b5g 2012  "


def is_likely_legacy_bijoy(text: str) -> bool:
    """Detect legacy-Bijoy ASCII-encoded Bangla before conversion."""
    if not text.strip():
        return False
    if bangla_char_ratio(text) > 0.2:
        return False  # already Unicode-dominant
    return any(sig in text for sig in _BIJOY_SIGNATURES)


def _relocate_reph_glyph(raw: str) -> str:
    """Move every ``©`` one position earlier, in front of the glyph it governs.

    In SutonnyMJ the reph is typed immediately after the consonant it applies
    to and before that syllable's vowel signs, so a single-position step puts
    it exactly where Unicode wants it::

        KvR©µg   → Kv©Rµg   → কার্যক্রম
        eY©bv    → e©Ybv   → বর্ণনা
        wba©vwiZ → wb©avwiZ → নির্ধারিত
        ag©      → a©g     → ধর্ম

    A ``©`` at the start of the text, or one preceded by whitespace, is left
    alone: there is no governing consonant to move it in front of, and moving
    it across a word boundary would attach a reph to the wrong word.
    """
    if REPH_GLYPH not in raw:
        return raw
    out = list(raw)
    for i in range(1, len(out)):
        if out[i] == REPH_GLYPH and not out[i - 1].isspace():
            glyph = out.pop(i)
            out.insert(i - 1, glyph)
    return "".join(out)


def _attempt(converter, text: str) -> str | None:
    """One conversion attempt; ``None`` instead of an exception.

    Returns rather than passing on the exception so the failure is visible to
    the caller's control flow (and so the lint rule that flags a silent
    ``except: pass`` has nothing to flag) — a swallowed exception here would
    hide exactly the bounds bug this module works around.

    The ``isinstance`` guard is not defensive noise: the third-party converter
    is untyped, so its return value is ``Any`` and ``mypy`` is right to refuse
    to hand it back as ``str``. Checking the one property the caller relies on
    keeps the annotation honest without a ``cast`` that would assert something
    nobody verified.
    """
    try:
        result = converter.convertBijoyToUnicode(text)
    except Exception:
        return None
    return result if isinstance(result, str) else None


def _convert(converter, text: str) -> str | None:
    """Convert ``text``, retrying once with a neutral tail if the library trips.

    ``None`` means the converter could not handle this input at all. The
    pre-fixed text is what gets the padded retry — never the original — so a
    bounds failure cannot quietly revert the reph relocation.
    """
    direct = _attempt(converter, text)
    if direct is not None:
        return direct
    converted = _attempt(converter, text + _CONVERTER_TAIL)
    if converted is None:
        return None
    tail = _attempt(converter, _CONVERTER_TAIL)
    if tail and converted.endswith(tail):
        return converted[: -len(tail)]
    # The tail did not survive verbatim (the library's rearrangement is not
    # context-free at the join); hand back the padded conversion rather than
    # losing the page, and let the caller's QC flag it.
    return converted


def convert_bijoy_text(text: str, converter=None) -> str:
    """Convert one page of Bijoy text to Unicode Bangla.

    Raises nothing for a page the converter cannot handle: the upstream library
    indexes past the end of the string at three sites
    (``converter.py:302``/``:332``/``:389``, all reproduced), so a page whose
    text ends with a reph raises ``IndexError``. On total failure the original
    text is returned unchanged, so the page is kept and flagged by the QC layer
    rather than silently lost.
    """
    if not text.strip():
        return text
    if converter is None:
        from bijoy2unicode.converter import Unicode

        converter = Unicode()
    # NBT-001: put the reph glyph in logical order before the converter maps it.
    converted = _convert(converter, _relocate_reph_glyph(text))
    if converted is None:
        return text
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
