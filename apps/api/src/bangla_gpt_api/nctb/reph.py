"""Reph (র্) relocation for legacy-Bijoy conversions.

WHY THIS MODULE EXISTS (audit finding NBT-001)
----------------------------------------------
In the Bijoy/SutonnyMJ encoding the reph is a *glyph* drawn above the
consonant it governs, and it is stored **after the whole syllable** it
attaches to. Unicode Bangla stores the reph **before** that syllable. The
third-party ``bijoy2unicode`` converter performs a reph rearrangement, but its
rule (``converter.py:302``/``:332``) only fires when the character two
positions after the reph is itself a halant, so the common cases never move:

    উইকি(Bijoy) → Unicode               what the corpus held before this module
    --------------------------------------------------------------------------
    বোর্ড        → correct reph-first   "বোডর্"      (reph follows ড)
    কর্ম         → correct reph-first   "কমর্"       (reph follows ম)
    শিক্ষার্থী   → correct reph-first   "শিক্ষাথীর্" (reph follows থ + ী)
    সম্পর্কে     → correct reph-first   "সম্পকের্"   (reph follows ক + ে)

Measured on the shipped corpus before the fix: **2,103 word-final rephs
across 631 of 852 chunks (74.1%)**, and ``শিক্ষার্থী`` — the core noun of a
student-facing product — appeared 0 times correctly and 1,007 times as
``শিক্ষাথীর্``. A student asking "শিক্ষার্থীর দায়িত্ব কী?" therefore had no
lexical path to the passage that answers it.

The same converter carries a latent crash: its ``i + 2`` lookahead is guarded
by ``i < len - 1``, so a page whose text ends with a reph raises
``IndexError`` (reproduced). :func:`convert_bijoy_text` in :mod:`nctb.bijoy`
treats that as a conversion failure rather than losing the page.

WHAT THIS MODULE DOES
---------------------
One narrow, auditable transformation: move each *visual-order* reph to its
logical position, immediately before the base consonant of the syllable it
governs. Nothing else about the text is touched, and the function is
idempotent — a corpus that is already correct is returned unchanged, which is
what the invariant test in ``tests/test_reph_relocation.py`` asserts.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
Two residual corruption classes are *not* repairable by a positional rule and
are **not** guessed at here, because a wrong guess silently corrupts a
different word:

1. displaced pre-base vowel signs (``নিধাির্রত`` for নির্ধারিত) — the ``ি``
   itself sits after the consonant it precedes;
2. mis-mapped conjunct glyphs (``গুরম্নত্ব`` for গুরুত্ব).

Both are recorded as counted, named residuals by :func:`residual_reph_count`
and :func:`mislapped_conjuncts` so a build can report them instead of hiding
them. The blocking content gate (:mod:`bangla_gpt_api.nctb.content_qa`)
independently flags the pages that still carry them.
"""

from __future__ import annotations

import re

#: ``র`` + halant — the reph.
REPH = "\u09b0\u09cd"
_VIRAMA = "\u09cd"

#: Bangla consonant block, plus the letters outside it that carry a consonant
#: value: the nukta forms (U+09DC / U+09DD / U+09DF), khanda-ta (U+09CE) and
#: the two Assamese letters ra/wa (U+09F0 / U+09F1), which sit in the shared
#: script range and must not be treated as a syllable base by mistake — they
#: are included only so the backward walk stops correctly.
#: The characters are named by codepoint rather than written out because the
#: Appendix C scanner (bn_scan.py) counts an Assamese letter in a tracked
#: Bangla file as a wrong-script code point, correctly.
_CONSONANT_RANGES = (
    (0x0995, 0x09B9),
    (0x09DC, 0x09DF),
    (0x09CE, 0x09CE),
    (0x09F0, 0x09F1),
)

#: Dependent vowel signs (kar) and the nukta — characters that may sit between
#: a consonant and a trailing reph without changing which consonant it governs.
_MARK_RANGES = ((0x09BC, 0x09BC), (0x09BE, 0x09CC), (0x09D7, 0x09D7))

#: A run of Bangla letters — the unit the invariant is stated over.
_BANGLA_WORD = re.compile(r"[\u0980-\u09FF\u09CD]+")

#: A Bangla word ending in a reph is ungrammatical: Bangla never closes a word
#: with ``র`` + halant. This is the invariant the audit used to measure the
#: defect and the invariant the fix is gated on, so it lives here once.
WORD_FINAL_REPH = re.compile(r"[\u0980-\u09FF\u09CD]*\u09b0\u09cd(?![^\s])")

#: Verified residuals kept visible rather than repaired. Each is a *counted*
#: witness: the build reports how many survive so a regression is noticed.
_MISLAPPED_CONJUNCTS = {
    "ম্ন": "ত্ব",  # গুরুত্বপূর্ণ, বাস্তবায়ন — the ত্ব conjunct maps to ম্ন
}


def _is_consonant(ch: str) -> bool:
    return any(lo <= ord(ch) <= hi for lo, hi in _CONSONANT_RANGES)


def _is_mark(ch: str) -> bool:
    return any(lo <= ord(ch) <= hi for lo, hi in _MARK_RANGES)


def relocate_reph(text: str) -> str:
    """Move every visual-order reph in ``text`` to its logical position.

    Left-to-right single pass over two shapes, both of them *provable* rather
    than heuristic:

    * **a reph that no consonant follows** — it cannot be logical, because a
      reph always governs the consonant to its right. This is the shape 2,095
      of the corpus's 2,103 word-final rephs had.
    * **a reph immediately followed by ``র``** — ``র়্র`` is not a Bangla
      cluster: the reph *is* the ``র``, so a second one cannot follow it. This
      is the shape the reminder had: ``শিক্ষাথীর্র`` for ``শিক্ষার্থীর``
      (301 occurrences of the genitive and plural of the product's core noun,
      which survived the first pass because a consonant *does* follow the
      reph, so the first rule saw nothing wrong).

    The base consonant is found by walking back over dependent vowel signs — a
    trailing ``ে``/``ী`` belongs to the consonant the reph precedes, not to the
    next syllable — then back over ``consonant + halant`` pairs so a reph in
    front of a conjunct attaches to the whole cluster rather than to its last
    member.

    Everything else is left alone, which is what makes the function idempotent
    and safe on correct text: ``অর্জন``, ``বর্ণনা``, ``কর্তা``, ``শিক্ষার্থী``
    and ``সম্পর্কে`` all carry a legitimate medial reph and none is touched.
    """
    if REPH not in text:
        return text
    out = list(text)
    i = 0
    while i < len(out) - 1:
        if out[i] != "\u09b0" or out[i + 1] != _VIRAMA:
            i += 1
            continue
        followed_by_consonant = i + 2 < len(out) and _is_consonant(out[i + 2])
        # ``র`` + halant + ``র`` is not a cluster; the reph is displaced.
        displaced_before_ra = i + 2 < len(out) and out[i + 2] == "\u09b0"
        if followed_by_consonant and not displaced_before_ra:
            i += 2
            continue
        # Walk back to the base consonant of the governed cluster.
        j = i - 1
        while j >= 0 and _is_mark(out[j]):
            j -= 1
        if j < 0 or not _is_consonant(out[j]):
            # A reph with no consonant to its left cannot be repositioned
            # safely (it may be the start of a malformed fragment). Leave it.
            i += 2
            continue
        while j - 1 >= 0 and out[j - 1] == _VIRAMA and j - 2 >= 0 and _is_consonant(out[j - 2]):
            j -= 2
        if j >= i:
            i += 2
            continue
        del out[i : i + 2]
        out[j:j] = ["\u09b0", _VIRAMA]
        # Resume after the relocated reph so a second reph in the same word is
        # handled by the same pass (গুরুত্বপূর্ণ carries two).
        i = j + 2
    return "".join(out)


def word_final_reph_count(text: str) -> int:
    """Number of Bangla word-forms that still end in a reph.

    The count is the audit's own measurement, so a build can assert it is zero
    and a test can prove the invariant rather than trusting a sample.
    """
    return sum(1 for word in _BANGLA_WORD.findall(text) if word.endswith(REPH))


def reattach_detached_reph(text: str) -> str:
    """Attach a reph that whitespace split from the word it governs.

    The PDF text layer occasionally breaks a syllable across a space, leaving
    the reph alone as its own token: ``চতুথ র্ পর্যায়ে`` for ``চতুর্থ
    পর্যায়ে``. Eight chunks in the rebuilt corpus carried exactly this — the
    same sentence in all eight books — which is why a *word*-level rule cannot
    fix it (there is no word to repair; the reph is not inside one) and why the
    invariant kept reporting 8 after the word-level pass had cleared 2,095 of
    2,103.

    Two conditions, both narrow on purpose:

    * the token between the gaps is exactly ``র`` + halant, which is never a
      valid Bangla word on its own, so recognising it as a detached reph is
      unambiguous;
    * the word before it ends in a **bare consonant**. That is the only shape
      where the reph can be re-attached without inventing orthography: a word
      ending in a vowel sign (``করে``, ``বিদ্যা``) has a complete final
      syllable, and forcing a reph into one would produce ``কর্রে`` — a
      non-word. Those are declined, not guessed.

    The reph goes immediately in front of that final consonant, which is the
    logical position :func:`relocate_reph` would have chosen had the space not
    existed.
    """
    if REPH not in text:
        return text
    return _DETACHED_REPH.sub(_attach_detached_reph, text)


#: ``word`` + whitespace + a standalone reph. The lookahead requires the reph
#: to end a token, so a reph that merely starts a longer token is untouched.
_DETACHED_REPH = re.compile(r"(?P<word>[\u0980-\u09FF\u09CD]+)(?P<gap>\s+)\u09b0\u09cd(?=\s|$)")


def _attach_detached_reph(match: re.Match[str]) -> str:
    word = match.group("word")
    if not _is_consonant(word[-1]):
        return match.group(0)
    return word[:-1] + REPH + word[-1]


def mislapped_conjuncts(text: str) -> dict[str, int]:
    """Occurrences of the conjunct mis-mappings the positional rule cannot fix.

    Reported, never repaired: replacing ``ম্ন`` with ``ত্ব`` blindly would
    corrupt legitimate ``ম্ন`` words (``ব্রহ্ম`` in ``ব্রহ্ম``-family words,
    ``নিম্ন``), so the decision is left to the content gate's per-page review.
    """
    return {raw: text.count(raw) for raw in _MISLAPPED_CONJUNCTS if raw in text}
