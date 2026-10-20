"""Structure-aware semantic chunking of extracted NCTB pages.

Hierarchy implemented (master §16/§17):
    Chapter (parent unit, detected from Bangla headings)
      └── Section-sized child chunks (retrieval units)

Boundaries prefer paragraph/heading lines and then *sentences*: the size
target is met by packing whole sentences (Bangla danda ``।``, ``?``, ``!``)
up to TARGET_WORDS, never by cutting a sentence in half. A sentence longer
than MAX_WORDS is the only case split on word boundaries (there is no
punctuation left to respect) and a merge that would overshoot MAX_WORDS is
split rather than truncated — the earlier implementation silently dropped
the overflow tail. Chapter/section/page provenance is preserved on every
chunk.

Chunk-size units are whitespace words (the pipeline has no tokenizer
dependency; §9 of docs/RAG_ARCHITECTURE.md records that decision). The
quality report carries the word-length histogram of every build so a
unit change is visible in the artifact, not only in this file.
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
    # Official curriculum format: "প্রথম অধ্যায়: বৈজ্ঞানিক প্রক্রিয়া এবং পরিমাপ"
    re.compile(r"^\s*(\S+)\s*অধ্যায়\s*[:：\-–]\s*(.+)$"),
]
SECTION_HINTS = ("অনুশীলনী", "অনুশীলন", "সংক্ষিপ্ত প্রশ্ন", "বহু নির্বাচনি", "পাঠ")

# pypdf often emits a whole page as ONE physical line where the running
# header glues onto the chapter heading ("… ২০১২ ৩৮ প্রথম অধ্যায়: …").
# Re-break before heading-shaped fragments so the anchored patterns match.
_HEADING_BREAK = re.compile(r"\s+(?=\S{1,12}\s*অধ্যায়\s*[:：])")
_SECTION_BREAK = re.compile(r"\s+(?=(?:অনুশীলনী|অনুশীলন|বহু\s*নির্বাচনি|সংক্ষিপ্ত\s*প্রশ্ন)\s*[?:।]?)")

# Sentence boundary: Bangla danda / question mark / exclamation mark followed
# by whitespace. ASCII '.' is deliberately NOT a boundary (the curriculum
# documents carry English abbreviations such as "M.Sc." inside Bangla prose).
_SENTENCE_SPLIT = re.compile(r"(?<=[।?!])\s+")

# Numbered curriculum headings in the schools' curriculum volumes
# ("৪.১ অবস্থা বিশ্লেষণ", "৬.৩ সাধারণ শিক্ষা ধারার …"), unlike textbook
# chapters. They are section-level boundaries, not chapters.
_NUMBERED_HEADING = re.compile(r"^[০-৯0-9]{1,2}(?:\.[০-৯0-9]{1,2})*[.)]?\s+\S")


def _restore_line_breaks(text: str) -> str:
    text = _HEADING_BREAK.sub("\n", text)
    return _SECTION_BREAK.sub("\n", text)


TARGET_WORDS = 220
MIN_WORDS = 60
MAX_WORDS = 400
#: sentences carried from the tail of one piece into the next (0 = off);
#: measured in the chunk-size ablation (scripts/ablate_nctb_chunking.py).
DEFAULT_OVERLAP_WORDS = 0


@dataclass
class RawChunk:
    chunk_id: str
    parent_id: str | None
    text: str  # normalized text used for indexing
    original_text: str
    chapter: str
    page_start: int
    page_end: int
    section: str = ""  # section heading the chunk belongs to ("" = none)
    #: A2-05: content-addressed hash of the final normalized chunk text,
    #: stamped by dedupe_chunks (the last text-defining step of a build) so
    #: every chunk record in *.chunks.jsonl carries its own checksum — the
    #: per-chunk analogue of the manifest's per-document sha256.
    content_hash: str = ""


def _stable_id(*parts: object) -> str:
    joined = "|".join(str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _text_fingerprint(text: str) -> str:
    """Normalized content hash for cross-page/edition duplicate detection."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def dedupe_chunks(chunks: list[RawChunk]) -> tuple[list[RawChunk], int]:
    """Drop byte-identical (post-normalization) chunks, keeping first wins.

    Overlapping PDF pages and reprinted editions otherwise index the same
    passage twice, diluting retrieval diversity. Every SURVIVOR carries its
    content hash (A2-05), so the artifacts store a per-chunk checksum.
    Returns ``(unique, removed)``.
    """
    seen: set[str] = set()
    unique: list[RawChunk] = []
    removed = 0
    for chunk in chunks:
        digest = _text_fingerprint(chunk.text)
        if digest in seen:
            removed += 1
            continue
        seen.add(digest)
        chunk.content_hash = digest
        unique.append(chunk)
    return unique, removed


def near_duplicate_groups(
    records: list[tuple[str, str, str]],
    *,
    threshold: float = 0.9,
    min_chars: int = 100,
) -> list[list[tuple[str, str]]]:
    """Cross-source near-duplicate detection over chunk texts (A2-05).

    Input: ``(chunk_id, source_id, text)`` triples. Two texts are near
    duplicates at character-trigram Jaccard >= ``threshold`` (identical
    texts compare at 1.0, so exact cross-source reprints measure here too —
    per-source exact dupes are already removed by dedupe_chunks). Short
    texts (< ``min_chars``) never pair: section headings legitimately repeat
    across books and carry too little content to judge. Cross-source only:
    a near-duplicate WITHIN one source is a chunking artifact, not a
    provenance/dedup finding. Groups with >= 2 members are returned with
    transitive closure, members sorted by (source_id, chunk_id).
    """
    from bangla_gpt_api.retrieval.hybrid import trigram_ngrams

    prepared = [
        (chunk_id, source_id, len(text), trigram_ngrams(text))
        for chunk_id, source_id, text in records
    ]
    n = len(prepared)
    parent = list(range(n))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        _id_i, source_i, len_i, grams_i = prepared[i]
        for j in range(i + 1, n):
            _id_j, source_j, len_j, grams_j = prepared[j]
            if source_i == source_j:
                continue
            if not grams_i or not grams_j:
                continue
            if min(len_i, len_j) < min_chars:
                continue  # short headings legitimately repeat; too little content
            union = len(grams_i | grams_j)
            if union and len(grams_i & grams_j) / union >= threshold:
                ri, rj = _find(i), _find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict[int, list[tuple[str, str]]] = {}
    for i, (chunk_id, source_id, _len, _grams) in enumerate(prepared):
        groups.setdefault(_find(i), []).append((source_id, chunk_id))
    return [sorted(members) for members in groups.values() if len(members) >= 2]


def _is_chapter_heading(line: str) -> str | None:
    for pattern in CHAPTER_PATTERNS:
        match = pattern.match(line)
        if match:
            # Ordinal form captures the title in group(2); others in group(1).
            groups = match.groups()
            title = groups[1] if len(groups) > 1 and groups[1] is not None else groups[0]
            return normalize_bangla(title)
    return None


def split_sentences(text: str) -> list[str]:
    """Split on Bangla danda/``?``/``!``; whitespace-collapsed input expected."""
    return [part for part in (p.strip() for p in _SENTENCE_SPLIT.split(text)) if part]


def _word_window(text: str, size: int) -> list[str]:
    """Hard word-boundary windowing, used only where no sentence fits."""
    words = text.split(" ")
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)]


def pack_sentences(
    text: str,
    *,
    target_words: int = TARGET_WORDS,
    min_words: int = MIN_WORDS,
    max_words: int = MAX_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
) -> list[str]:
    """Pack whole sentences up to ``target_words`` per piece.

    * a sentence longer than ``max_words`` is split on word boundaries
      (nothing left to respect inside it);
    * a trailing piece below ``min_words`` merges into the previous piece;
    * ``overlap_words`` repeats that many trailing words of each piece at
      the start of the next (0 keeps the historical no-overlap behaviour);
    * pieces larger than ``max_words`` are split, never truncated — the
      pre-2026-10-18 implementation dropped the overflow tail silently.
    """
    sentences: list[str] = []
    for sentence in split_sentences(text):
        if len(sentence.split(" ")) > max_words:
            sentences.extend(_word_window(sentence, target_words))
        else:
            sentences.append(sentence)

    pieces: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        size = len(sentence.split(" "))
        if current and len(current) + size > target_words and len(current) >= min_words:
            pieces.append(" ".join(current))
            current = current[-overlap_words:] if overlap_words > 0 else []
        current.extend(sentence.split(" "))

    if current:
        if pieces and len(current) < min_words:
            pieces[-1] = f"{pieces[-1]} {' '.join(current)}"
        else:
            pieces.append(" ".join(current))

    bounded: list[str] = []
    for piece in pieces:
        if len(piece.split(" ")) > max_words:
            bounded.extend(_word_window(piece, max_words))
        else:
            bounded.append(piece)
    return bounded


def chunk_pages(
    pages: list[PageText],
    *,
    source_id: str,
    target_words: int = TARGET_WORDS,
    min_words: int = MIN_WORDS,
    max_words: int = MAX_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
    stats: dict | None = None,
) -> list[RawChunk]:
    """Build chapter-parented, section-aware chunks with page provenance.

    ``stats`` (optional, additive) receives ``short_blocks_merged`` and
    ``chunk_word_lengths`` so the corpus report can carry the chunk-size
    histogram without a second pass over the chunks.
    """
    chunks: list[RawChunk] = []
    current_chapter = ""
    current_section = ""
    buffer_lines: list[str] = []
    buffer_pages: set[int] = set()
    buffer_section = ""
    chapter_seq = 0
    short_blocks = 0

    def flush(*, merge_forward: bool = False) -> None:
        nonlocal buffer_lines, buffer_pages, buffer_section, short_blocks
        if not buffer_lines:
            return
        text = normalize_bangla(" ".join(buffer_lines))
        words = text.split(" ") if text else []
        if len(words) < min_words:
            # Too small to stand alone: hold it for the next block instead of
            # dropping content (the old behaviour lost every short block).
            short_blocks += 1
            if merge_forward:
                return
            if not chunks:
                buffer_lines, buffer_pages, buffer_section = [], set(), ""
                return
            tail = " ".join(buffer_lines)
            last = chunks[-1]
            merged = f"{last.text} {tail}".strip()
            chunks[-1] = RawChunk(
                chunk_id=last.chunk_id,
                parent_id=last.parent_id,
                text=merged,
                original_text=last.original_text,
                chapter=last.chapter,
                page_start=last.page_start,
                page_end=max(last.page_end, max(buffer_pages) if buffer_pages else last.page_end),
                section=last.section,
            )
            buffer_lines, buffer_pages, buffer_section = [], set(), ""
            return
        for piece in pack_sentences(
            text,
            target_words=target_words,
            min_words=min_words,
            max_words=max_words,
            overlap_words=overlap_words,
        ):
            parent_id = (
                _stable_id(source_id, "chapter", chapter_seq, current_chapter)
                if current_chapter
                else None
            )
            # A20: the id hashes the FULL text (plus chapter sequence), not
            # the first 80 chars — two chunks sharing a boilerplate prefix
            # and a page used to collide into one id.
            chunks.append(
                RawChunk(
                    chunk_id=_stable_id(source_id, "chunk", chapter_seq, min(buffer_pages), piece),
                    parent_id=parent_id,
                    text=piece,
                    original_text=" ".join(buffer_lines)[: len(piece) * 2],
                    chapter=current_chapter,
                    page_start=min(buffer_pages),
                    page_end=max(buffer_pages),
                    section=buffer_section,
                )
            )
        buffer_lines, buffer_pages, buffer_section = [], set(), ""

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
                current_section = ""
                continue
            normalized_line = normalize_bangla(stripped)
            is_section_marker = (
                any(hint in normalized_line for hint in SECTION_HINTS) and len(normalized_line) < 60
            )
            if not is_section_marker and _NUMBERED_HEADING.match(normalized_line):
                # Numbered curriculum heading; only a break once the current
                # block can stand alone, so numbered *lists* inside prose
                # never fragment into sub-minimum fragments.
                is_section_marker = sum(len(line.split()) for line in buffer_lines) >= min_words
            if is_section_marker:
                flush(merge_forward=True)
                if not buffer_lines:
                    current_section = normalized_line[:80]
            if not buffer_lines:
                buffer_section = current_section
            buffer_lines.append(normalized_line)
            buffer_pages.add(page.page_number)
            projected = sum(len(line.split()) for line in buffer_lines)
            if projected >= target_words + 120:
                flush()
    flush()
    if stats is not None:
        # Sub-minimum blocks were merged into a neighbouring chunk, never
        # dropped; the count makes that visible in the corpus report.
        stats["short_blocks_merged"] = short_blocks
        stats["chunk_word_lengths"] = [len(chunk.text.split(" ")) for chunk in chunks]
    return chunks
