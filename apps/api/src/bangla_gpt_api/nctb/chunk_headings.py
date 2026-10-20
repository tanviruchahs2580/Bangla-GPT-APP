"""Chapter and section heading detection for the NCTB chunker.

Extracted from ``chunking.py`` for cohesion: every pattern here answers "is
this line a chapter/section heading, and what is its stable label?" against
the printed shapes measured on the 2026-10-20 extracted pages
(docs/NCTB_DATA_PIPELINE.md §3). Conservative by construction — an unclear
candidate returns None rather than a guessed label.
"""

from __future__ import annotations

import re
import unicodedata

from bangla_gpt_api.nctb.normalize import normalize_bangla

MAX_CHAPTER_TITLE_WORDS = 7
_SECTION_BREAK = re.compile(r"\s+(?=(?:অনুশীলনী|অনুশীলন|বহু\s*নির্বাচনি|সংক্ষিপ্ত\s*প্রশ্ন)\s*[?:।]?)")

#: Bangla ordinals that precede "অধ্যায়" in these curriculum volumes. Measured
#: on the extracted pages (2026-10-20): the real heading shape is
#: "<ordinal> অধ্যায় [number] [:：] <title>", e.g. "প্রথম অধ্যায়: ভৌতজগত ও
#: পরিমাপ", "দ্বিতীয় অধ্যায় ভেক্টর", "চতুথর্ অধ্যায় ৪ : নিউটনিয়ান বলবিদ্যা".
#: "চতুথর্"/"চতুদর্শ" are the documented legacy-conversion conjunct reorderings
#: of চতুর্থ/চতুর্দশ (docs/NCTB_DATA_PIPELINE.md §3); they are accepted here and
#: repaired in the emitted label, because a real heading is a real heading.
SECTION_HINTS = ("অনুশীলনী", "অনুশীলন", "সংক্ষিপ্ত প্রশ্ন", "বহু নির্বাচনি", "পাঠ")

CHAPTER_ORDINALS = (
    "প্রথম",
    "দ্বিতীয়",
    "তৃতীয়",
    "চতুর্থ",
    "চতুথর্",
    "চতুর্দশ",
    "চতুদর্শ",
    "পঞ্চম",
    "ষষ্ঠ",
    "সপ্তম",
    "অষ্টম",
    "নবম",
    "দশম",
    "একাদশ",
    "দ্বাদশ",
)


#: title words, which are left exactly as extracted).
_ORDINAL_ALT = "|".join(CHAPTER_ORDINALS)

_ORDINAL_REPAIRS = {"চতুথর্": "চতুর্থ", "চতুদর্শ": "চতুর্দশ"}


#: Words that continue a PROSE sentence after "<ordinal> অধ্যায়" — "প্রথম
#: অধ্যায় থেকে কী কী জ্ঞান …" is a curriculum sentence, not a heading. A
#: candidate whose title starts with one of these is rejected (a wrong chapter
#: label is worse than ""). Measured conservatism: on the real corpus this
#: rejects exactly the sentence-shaped candidates (see the A2-04 evidence).
_PROSE_CONTINUATIONS = frozenset(
    {
        "থেকে",
        "শেষে",
        "শুরুতে",
        "সম্পর্কে",
        "সমূহ",
        "সমূহকে",
        "সমূহের",
        "ব্যাপী",
        "ভিত্তিক",
        "ভিত্তিতে",
        "জুড়ে",
        "নিয়ে",
        "অনুযায়ী",
        "অভীক্ষা",
        "থাকবে",
        "রয়েছে",
        "হবে",
    }
)


CHAPTER_PATTERNS = [
    # Ordinal form (the real shape in these volumes); optional chapter number
    # and colon between "অধ্যায়" and the title.
    re.compile(
        rf"^\s*(?P<ordinal>{_ORDINAL_ALT})\s*অধ্যায়\s*(?:[০-৯0-9]{{1,2}}\s*)?"
        r"[:：\-–]?\s*(?P<title>.*)$"
    ),
    # Plain textbook form without an ordinal: "অধ্যায়: কোষ", "অধ্যায় ৫ কোষ".
    re.compile(r"^\s*(?:উত্তর\s*)?অধ্যায়\s*(?:[০-৯0-9]{1,2}\s*)?[:：\-–]?\s*(?P<title>.+)$"),
    re.compile(r"^\s*অধ্যায়ে?র?\s*নাম\s*[:：\-–]?\s*(?P<title>.+)$"),
]


# pypdf often emits a whole page as ONE physical line where the running
# header glues onto the chapter heading ("… ২০১২ ৩৮ প্রথম অধ্যায়: …").
# Re-break before heading-shaped fragments so the anchored patterns match.
# Two shapes are broken: the ordinal form (with or without a colon, which is
# how the real chapters appear) and the colon form for headings whose ordinal
# is not in CHAPTER_ORDINALS.
_COLON_HEADING_BREAK = re.compile(r"\s+(?=\S{1,12}\s*অধ্যায়\s*[:：])")
_HEADING_BREAK = re.compile(rf"\s+(?=(?:{_ORDINAL_ALT})\s*অধ্যায়\s*[:：]?\s*\S)")


#: Column/cell words of the curriculum's class-wise tables. A candidate whose
#: title STARTS with one of these is a chapter reference cell, not a heading:
#: the row is "ষষ্ঠ শ্রেণি প্রথম অধ্যায় …" / "প্রথম অধ্যায় প্রান্ত্মিক শিখনফল …"
#: and the text that follows belongs to the next COLUMN, so the chapter name is
#: not recoverable there. Rejected — a wrong chapter label is worse than "".
#: The same words can legitimately END a title (… "শিখনফল : ১. …"), where the
#: title is truncated at the marker instead.
_CELL_MARKERS = (
    "শ্রেণি",
    "শ্রেণিভিত্তিক",
    "শিখনফল",
    "শিখনফলের",
    "প্রান্ত্মিক",
    "স্ত্মরভিত্তিক",
    "বিষয়ভিত্তিক",
    "উদ্দেশ্য",
    "বিষয়বস্তু",
    "পিরিয়ড",
    "যোগ্যতা",
)


#: Prose words that never appear inside a chapter NAME. A candidate whose title
#: contains one is a sentence that merely starts with a chapter reference
#: ("প্রাণীর আচরণ অধ্যায়টি নতুন বিধায় …", "… যেগুলো অন্যেরা করে চলমান") — its
#: name is cut off where the prose continues (see _title_cut) or rejected.
_PROSE_TITLE_WORDS = ("যেগুলো", "যেগুলি", "যেটি", "হবে", "নেই", "বিধায়", "করতে")


#: A chapter label never exceeds this many characters, and an overlong title
#: is truncated at a word boundary rather than put in metadata whole.
MAX_CHAPTER_LABEL_CHARS = 80


#: Leading/trailing punctuation and bare numbers ("16" = the period count in
#: the curriculum's chapter table, "৪." a list number) are not part of a title.
_LABEL_TRIM = re.compile(r"^[\s০-৯0-9.,:;।\-–]+|[\s০-৯0-9.,:;।\-–]+$")


#: "(গধঃৎরপং …)"), where the sentence does (danda / semicolon), or where the
#: curriculum table continues with the next column's numbers ("ভৌতজগত ও
#: পরিমাপ 16 প্রথম অধ্যায় …", "পরিমাপ ১. উদাহরণের …").
_TITLE_CUT = re.compile(r"[।;]|\(|\s[০-৯0-9]{1,3}(?=[\s.)।]|$)")


def _truncate_at_marker(title: str) -> str:
    """Cut the title where a curriculum-table column marker begins."""
    cut = len(title)
    for marker in _CELL_MARKERS:
        found = title.find(marker)
        if found > 0:
            cut = min(cut, found)
    return title[:cut].strip()


def _title_words(title: str) -> list[str]:
    """Words of the candidate title after the punctuation/number trim."""
    cleaned = _TITLE_CUT.split(title, maxsplit=1)[0]
    return normalize_bangla(_LABEL_TRIM.sub("", cleaned)).split()


def _is_rejected_title(words: list[str]) -> bool:
    """True when the candidate is prose or a curriculum-table cell, not a name."""
    if not words:
        return False
    if words[0] in _PROSE_CONTINUATIONS:
        return True
    if any(any(marker in word for marker in _CELL_MARKERS) for word in words[:2]):
        return True
    return bool(unicodedata.combining(words[0][0]))


def _chapter_name(words: list[str]) -> str:
    """Name part of a heading: first MAX words, cut at "অধ্যায়"/markers/gloss."""
    name = " ".join(words[:MAX_CHAPTER_TITLE_WORDS])
    later = name.find("অধ্যায়")
    if later > 0:
        name = name[:later].strip()
    return _truncate_at_marker(name).strip()


def _ordinal_prefix(ordinal: str | None) -> str:
    """The repaired ordinal as a label prefix ("চতুথর্" -> "চতুর্থ অধ্যায়")."""
    resolved = normalize_bangla(ordinal) if ordinal else ""
    if not resolved:
        return ""
    return f"{_ORDINAL_REPAIRS.get(resolved, resolved)} অধ্যায়"


def _bounded_label(label: str) -> str:
    """Trim an overlong label at a word boundary."""
    if len(label) <= MAX_CHAPTER_LABEL_CHARS:
        return label
    return label[:MAX_CHAPTER_LABEL_CHARS].rsplit(" ", 1)[0]


def _clean_chapter_title(ordinal: str | None, title: str) -> str | None:
    """Turn a matched heading into a stable chapter label, or None.

    Conservative by construction: a candidate whose title starts a prose
    sentence or a curriculum-table column ("প্রথম অধ্যায় থেকে কী কী জ্ঞান …",
    "প্রথম অধ্যায় প্রান্ত্মিক শিখনফল …") is rejected instead of recorded, and a
    title-less heading falls back to its ordinal ("প্রথম অধ্যায়") — the heading
    itself, never invented content. The ordinal is repaired ("চতুথর্" ->
    "চতুর্থ") because that is a conversion artifact of the extraction, not the
    source's spelling; title words are kept verbatim.
    """
    words = _title_words(title)
    if _is_rejected_title(words):
        return None
    prefix = _ordinal_prefix(ordinal)
    name = _chapter_name(words)
    if any(word in name for word in _PROSE_TITLE_WORDS):
        return None
    if not name:
        return prefix or None
    return _bounded_label(f"{prefix}: {name}" if prefix else name)


def _is_chapter_heading(line: str) -> str | None:
    for pattern in CHAPTER_PATTERNS:
        match = pattern.match(line)
        if match:
            groups = match.groupdict()
            return _clean_chapter_title(groups.get("ordinal"), groups.get("title") or "")
    return None
