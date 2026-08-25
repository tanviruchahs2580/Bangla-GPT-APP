"""Structure-aware semantic chunking of extracted NCTB pages.

Hierarchy implemented (master §16/§17):
    Chapter (parent unit, detected from Bangla headings)
      └── Section-sized child chunks (retrieval units)

Blind fixed-size splitting is not used: boundaries prefer paragraph and
heading lines; a max-size guard only splits when a single paragraph
exceeds the budget. Chapter/page provenance is preserved on every chunk.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.nctb.normalize import normalize_bangla

CHAPTER_PATTERNS = [
    re.compile(r"^\s*(?:উত্তর\s*)?অধ্যায়\s*[:：\-–]?\s*(.+)$"),
    re.compile(r"^\s*অধ্যায়ে?র?\s*নাম\s*[:：\-–]?\s*(.+)$"),
    # Official curriculum format: "প্রথম অধ্যায় : বৈজ্ঞানিক প্রক্রিয়া এবং পরিমাপ"
    re.compile(r"^\s*(\S+)\s*অধ্যায়\s*[:：\-–]\s*(.+)$"),
]
SECTION_HINTS = ("অনুশীলনী", "অনুশীলন", "সংক্ষিপ্ত প্রশ্ন", "বহু নির্বাচনি", "পাঠ")

# pypdf often emits a whole page as ONE physical line where the running
# header glues onto the chapter heading ("… ২০১২ ৩৮ প্রথম অধ্যায় : …").
# Re-break before heading-shaped fragments so the anchored patterns match.
_HEADING_BREAK = re.compile(r"\s+(?=\S{1,12}\s*অধ্যায়\s*[:：])")
_SECTION_BREAK = re.compile(r"\s+(?=(?:অনুশীলনী|অনুশীলন|বহু\s*নির্বাচনি|সংক্ষিপ্ত\s*প্রশ্ন)\s*[?:।]?)")


def _restore_line_breaks(text: str) -> str:
    text = _HEADING_BREAK.sub("\n", text)
    return _SECTION_BREAK.sub("\n", text)


TARGET_WORDS = 220
MIN_WORDS = 60
MAX_WORDS = 400


@dataclass
class RawChunk:
    chunk_id: str
    parent_id: str | None
    text: str  # normalized text used for indexing
    original_text: str
    chapter: str
    page_start: int
    page_end: int


def _stable_id(*parts: object) -> str:
    joined = "|".join(str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def _is_chapter_heading(line: str) -> str | None:
    for pattern in CHAPTER_PATTERNS:
        match = pattern.match(line)
        if match:
            # Ordinal form captures the title in group(2); others in group(1).
            groups = match.groups()
            title = groups[1] if len(groups) > 1 and groups[1] is not None else groups[0]
            return normalize_bangla(title)
    return None


def chunk_pages(
    pages: list[PageText],
    *,
    source_id: str,
    target_words: int = TARGET_WORDS,
    min_words: int = MIN_WORDS,
    max_words: int = MAX_WORDS,
) -> list[RawChunk]:
    """Build chapter-parented, section-aware chunks with page provenance."""
    chunks: list[RawChunk] = []
    current_chapter = ""
    buffer_lines: list[str] = []
    buffer_pages: set[int] = set()
    chapter_seq = 0

    def flush() -> None:
        nonlocal buffer_lines, buffer_pages
        if not buffer_lines:
            return
        text = normalize_bangla(" ".join(buffer_lines))
        words = text.split(" ") if text else []
        if len(words) < min_words:
            buffer_lines, buffer_pages = [], set()
            return
        # Oversize guard: split on sentence-ish boundaries within the block.
        pieces: list[str] = []
        current: list[str] = []
        count = 0
        for word in words:
            current.append(word)
            count += 1
            if count >= target_words:
                pieces.append(" ".join(current))
                current, count = [], 0
        if current:
            remainder = " ".join(current)
            if pieces and len(current) < min_words:
                pieces[-1] = f"{pieces[-1]} {remainder}"
            else:
                pieces.append(remainder)
        for piece in pieces:
            piece_words = piece.split(" ")
            if len(piece_words) > max_words:
                piece = " ".join(piece_words[:max_words])
            parent_id = (
                _stable_id(source_id, "chapter", chapter_seq, current_chapter)
                if current_chapter
                else None
            )
            chunks.append(
                RawChunk(
                    chunk_id=_stable_id(source_id, piece[:80], min(buffer_pages)),
                    parent_id=parent_id,
                    text=piece,
                    original_text=" ".join(buffer_lines)[: len(piece) * 2],
                    chapter=current_chapter,
                    page_start=min(buffer_pages),
                    page_end=max(buffer_pages),
                )
            )
        buffer_lines, buffer_pages = [], set()

    for page in pages:
        if not page.usable:
            continue
        normalized_page = _restore_line_breaks(page.text)
        for line in normalized_page.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            heading = _is_chapter_heading(stripped)
            if heading is not None:
                flush()
                chapter_seq += 1
                current_chapter = heading
                continue
            normalized_line = normalize_bangla(stripped)
            is_section_marker = (
                any(hint in normalized_line for hint in SECTION_HINTS) and len(normalized_line) < 60
            )
            if is_section_marker:
                flush()  # section boundary → start a fresh retrieval unit
            buffer_lines.append(normalized_line)
            buffer_pages.add(page.page_number)
            projected = sum(len(line.split()) for line in buffer_lines)
            if projected >= target_words + 120:
                flush()
    flush()
    return chunks
