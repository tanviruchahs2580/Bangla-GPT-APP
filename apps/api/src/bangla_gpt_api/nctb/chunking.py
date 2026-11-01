"""Structure-aware semantic chunking of extracted NCTB pages.

Hierarchy implemented (master §16/§17):
    Chapter (parent unit, detected from Bangla headings)
      └── Section-sized child chunks (retrieval units)

Blind fixed-size splitting is not used: boundaries prefer paragraph and
heading lines; a size guard caps what a single paragraph may contribute.
Chapter/page provenance is preserved on every chunk.

Two properties matter beyond the boundaries:

* sizes are counted in the tokens of the tokenizer the index actually uses
  (``retrieval.hybrid.tokenize``), not whitespace words (F-134);
* every chunk carries :class:`SourceSpan` runs mapping its text back onto the
  extracted page text, which is what a highlight needs; ``original_text`` is
  the exact source slice, not a re-sliced guess (F-133).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.nctb.normalize import (
    NormalizedText,
    normalize_bangla,
    normalize_bangla_with_offsets,
)
from bangla_gpt_api.retrieval.hybrid import tokenize

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


#: Size unit and budgets. The unit is the production tokenizer's token
#: (F-134); the numbers are anchored on the measured distribution of the
#: corpus build (docs/NCTB_DATA_PIPELINE.md §5, 805 chunks): p50 220 tokens,
#: p90 251, p95 273, max 430. TARGET is the measured median, MIN drops
#: fragments below the measured p5, MAX sits above the measured maximum so
#: it only guards a pathological single block.
SIZE_UNIT = "tokens"
TARGET_TOKENS = 220
MIN_TOKENS = 60
MAX_TOKENS = 450
#: Name of the shared normalizer the chunk text is stored in; recorded in the
#: corpus manifest so a stored corpus can be tied to its normalization.
NORMALIZER_NAME = "nfkc+zero-width+whitespace"

#: Flush threshold for the line buffer: the target plus one section's worth
#: of overshoot, so a boundary is taken at the next line instead of mid-line.
_FLUSH_HEADROOM = 120


@dataclass(frozen=True)
class SourceSpan:
    """A run of chunk text that maps onto one extracted page's text.

    ``page_text[page_start:page_end]`` is the source of
    ``text[text_start:text_end]`` for page ``page`` of the extracted
    artifact. The runs are ordered and non-overlapping; together with the
    page number they are the offset map from normalized text back to the
    original (F-133).
    """

    text_start: int
    text_end: int
    page: int
    page_start: int
    page_end: int


@dataclass
class RawChunk:
    chunk_id: str
    parent_id: str | None
    text: str  # normalized text used for indexing
    original_text: str
    chapter: str
    page_start: int
    page_end: int
    source_spans: list[SourceSpan] = field(default_factory=list)


def _map_offset(span: SourceSpan, text_offset: int) -> int:
    """Page offset for a text offset inside ``span``.

    Equal-length runs map 1:1; a run whose source range is longer or shorter
    (a collapsed whitespace run, a compatibility expansion) maps
    proportionally, which keeps the offset inside the run.
    """
    text_len = span.text_end - span.text_start
    page_len = span.page_end - span.page_start
    if text_len <= 0:
        return span.page_start
    if text_len == page_len:
        return span.page_start + text_offset
    return span.page_start + round(text_offset * page_len / text_len)


def _clip_spans(spans: list[SourceSpan], start: int, end: int) -> list[SourceSpan]:
    """Spans covering text ``[start, end)``, rebased so ``start`` becomes 0."""
    clipped: list[SourceSpan] = []
    for span in spans:
        overlap_start = max(span.text_start, start)
        overlap_end = min(span.text_end, end)
        if overlap_start >= overlap_end:
            continue
        page_start = _map_offset(span, overlap_start - span.text_start)
        page_end = max(_map_offset(span, overlap_end - span.text_start), page_start + 1)
        clipped.append(
            SourceSpan(
                text_start=overlap_start - start,
                text_end=overlap_end - start,
                page=span.page,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return clipped


def highlight_spans(chunk: RawChunk, start: int, end: int) -> list[SourceSpan]:
    """Source spans covering ``chunk.text[start:end]``, clipped and rebased.

    The caller (a highlight or a citation) passes a span of the chunk text it
    wants to show; the returned spans point into the extracted page text.
    """
    if start >= end:
        return []
    return _clip_spans(chunk.source_spans, start, end)


def _stable_id(*parts: object) -> str:
    joined = "|".join(str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _text_fingerprint(text: str) -> str:
    """Normalized content hash for cross-page/edition duplicate detection."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def dedupe_chunks(chunks: list[RawChunk]) -> tuple[list[RawChunk], int]:
    """Drop byte-identical (post-normalization) chunks, keeping first wins.

    Overlapping PDF pages and reprinted editions otherwise index the same
    passage twice, diluting retrieval diversity. Returns ``(unique, removed)``.
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
        unique.append(chunk)
    return unique, removed


def _is_chapter_heading(line: str) -> str | None:
    for pattern in CHAPTER_PATTERNS:
        match = pattern.match(line)
        if match:
            # Ordinal form captures the title in group(2); others in group(1).
            groups = match.groups()
            title = groups[1] if len(groups) > 1 and groups[1] is not None else groups[0]
            return normalize_bangla(title)
    return None


def _break_before(pattern: re.Pattern[str], text: str) -> tuple[str, list[int]]:
    """Insert a newline before every pattern match, keeping an index map.

    The matched whitespace run collapses into the single newline, which maps
    to the run's first character; all other characters map 1:1 to the input.
    """
    out: list[str] = []
    index_map: list[int] = []
    position = 0
    for match in pattern.finditer(text):
        out.append(text[position : match.start()])
        index_map.extend(range(position, match.start()))
        out.append("\n")
        index_map.append(match.start())
        position = match.end()
    out.append(text[position:])
    index_map.extend(range(position, len(text)))
    return "".join(out), index_map


def _restore_line_breaks_with_map(text: str) -> tuple[str, list[int]]:
    """Un-glue glued lines and return the map back into ``text``."""
    broken, heading_map = _break_before(_HEADING_BREAK, text)
    broken, section_map = _break_before(_SECTION_BREAK, broken)
    return broken, [heading_map[index] for index in section_map]


def _segments_from_offsets(
    normalized: NormalizedText, line_abs: list[int]
) -> list[tuple[int, int, int, int]]:
    """Runs ``(text_start, text_end, page_start, page_end)``, exact by cluster.

    ``line_abs[j]`` is the page-text index of the j-th character of the input
    line, so a cluster produced from input ``[a, b)`` covers the page range
    ``[line_abs[a], line_abs[b-1] + 1)``. Adjacent clusters merge while both
    are length-equal (text and source characters) and their source ranges
    continue 1:1: a run is therefore always individually round-trippable and
    clipping inside a run is exact. A cluster whose normalization expands
    (one input character becoming several output characters, e.g. ``¨`` ->
    space + diaeresis) stays one run covering exactly its source, and a
    collapsed whitespace run stays a one-character run covering the run.
    """
    offsets = normalized.offsets
    starts = normalized.cluster_starts or tuple(range(len(offsets)))
    segments: list[tuple[int, int, int, int]] = []
    for position, cluster_start in enumerate(starts):
        cluster_end = starts[position + 1] if position + 1 < len(starts) else len(offsets)
        if cluster_end <= cluster_start:
            continue
        source_start = offsets[cluster_start][0]
        source_end = offsets[cluster_end - 1][1]
        page_start = line_abs[source_start]
        page_end = line_abs[source_end - 1] + 1
        text_len = cluster_end - cluster_start
        page_len = page_end - page_start
        if segments:
            text_start, text_end, prev_page_start, prev_page_end = segments[-1]
            merged_len = text_end - text_start
            if (
                text_end == cluster_start
                and prev_page_end == page_start
                and merged_len == prev_page_end - prev_page_start
                and text_len == page_len
            ):
                segments[-1] = (text_start, cluster_end, prev_page_start, page_end)
                continue
        segments.append((cluster_start, cluster_end, page_start, page_end))
    return segments


@dataclass
class _Line:
    """One normalized line with its span map, ready to join into a buffer."""

    text: str
    page: int
    #: (line_text_start, line_text_end, page_text_start, page_text_end) runs
    segments: list[tuple[int, int, int, int]]


def _buffered_text(lines: list[_Line]) -> tuple[str, list[SourceSpan]]:
    """Join lines with single spaces and build the global span runs."""
    parts: list[str] = []
    spans: list[SourceSpan] = []
    cursor = 0
    for line in lines:
        if parts:
            parts.append(" ")
            cursor += 1
        parts.append(line.text)
        for text_start, text_end, page_start, page_end in line.segments:
            spans.append(
                SourceSpan(
                    text_start=cursor + text_start,
                    text_end=cursor + text_end,
                    page=line.page,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
        cursor += len(line.text)
    _merge_spans(spans)
    return "".join(parts), spans


def _merge_spans(spans: list[SourceSpan]) -> None:
    """Merge adjacent, length-equal, source-contiguous runs in place.

    Runs with unequal text/source lengths (a collapsed whitespace run, a
    compatibility expansion) stay separate so every span remains exact.
    """
    write = 0
    for span in spans:
        if write:
            previous = spans[write - 1]
            same_page = previous.page == span.page
            contiguous = previous.page_end == span.page_start
            previous_len = previous.text_end - previous.text_start
            equal_previous = previous_len == previous.page_end - previous.page_start
            span_len = span.text_end - span.text_start
            equal_span = span_len == span.page_end - span.page_start
            if (
                previous.text_end == span.text_start
                and same_page
                and contiguous
                and equal_previous
                and equal_span
            ):
                spans[write - 1] = SourceSpan(
                    text_start=previous.text_start,
                    text_end=span.text_end,
                    page=span.page,
                    page_start=previous.page_start,
                    page_end=span.page_end,
                )
                continue
        spans[write] = span
        write += 1
    del spans[write:]


def _word_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) character spans of ``text.split(" ")`` fields."""
    spans: list[tuple[int, int]] = []
    position = 0
    for word in text.split(" "):
        spans.append((position, position + len(word)))
        position += len(word) + 1
    return spans


def _token_count(text: str) -> int:
    return len(tokenize(text))


def chunk_pages(
    pages: list[PageText],
    *,
    source_id: str,
    target_tokens: int = TARGET_TOKENS,
    min_tokens: int = MIN_TOKENS,
    max_tokens: int = MAX_TOKENS,
) -> list[RawChunk]:
    """Build chapter-parented, section-aware chunks with page provenance."""
    chunks: list[RawChunk] = []
    current_chapter = ""
    buffer: list[_Line] = []
    buffer_tokens = 0
    chapter_seq = 0

    def flush() -> None:
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        text, spans = _buffered_text(buffer)
        lines, buffer, buffer_tokens = buffer, [], 0
        if not text:
            return
        words = _word_spans(text)
        word_tokens = [_token_count(text[start:end]) for start, end in words]
        if sum(word_tokens) < min_tokens:
            return
        # Pack words up to the target, merge a thin tail into the last piece.
        pieces: list[tuple[int, int]] = []
        piece_start: int | None = None
        consumed = 0
        for (start, end), count in zip(words, word_tokens, strict=True):
            if piece_start is None:
                piece_start = start
            consumed += count
            if consumed >= target_tokens:
                pieces.append((piece_start, end))
                piece_start, consumed = None, 0
        if piece_start is not None and words:
            tail = (piece_start, words[-1][1])
            if pieces and consumed < min_tokens:
                pieces[-1] = (pieces[-1][0], tail[1])
            else:
                pieces.append(tail)
        page_numbers = sorted({line.page for line in lines})
        for start, end in pieces:
            if _token_count(text[start:end]) > max_tokens:
                # Trim at the last word that still fits; the first word always
                # survives, so the cap can never produce an empty chunk.
                cut, used = None, 0
                for (_word_start, word_end), count in zip(words, word_tokens, strict=True):
                    if word_end <= start:
                        continue
                    if cut is not None and used + count > max_tokens:
                        break
                    used += count
                    cut = word_end
                if cut is not None:
                    end = cut
            piece_spans = _clip_spans(spans, start, end)
            parent_id = (
                _stable_id(source_id, "chapter", chapter_seq, current_chapter)
                if current_chapter
                else None
            )
            # A20: the id hashes the FULL text (plus chapter sequence), not
            # the first 80 chars — two chunks sharing a boilerplate prefix
            # and a page used to collide into one id.
            chunk_text = text[start:end]
            chunks.append(
                RawChunk(
                    chunk_id=_stable_id(
                        source_id, "chunk", chapter_seq, min(page_numbers), chunk_text
                    ),
                    parent_id=parent_id,
                    text=chunk_text,
                    original_text=_original_text(piece_spans, pages),
                    chapter=current_chapter,
                    page_start=min(page_numbers),
                    page_end=max(page_numbers),
                    source_spans=piece_spans,
                )
            )

    for page in pages:
        if not page.usable:
            continue
        restored, restore_map = _restore_line_breaks_with_map(page.text)
        line_start = 0
        for raw_line in restored.split("\n"):
            line = raw_line.strip()
            if line:
                lead = len(raw_line) - len(raw_line.lstrip())
                stripped_start = line_start + lead
                heading = _is_chapter_heading(line)
                if heading is not None:
                    flush()
                    chapter_seq += 1
                    current_chapter = heading
                else:
                    if any(hint in line for hint in SECTION_HINTS) and len(line) < 60:
                        flush()  # section boundary -> a fresh retrieval unit
                    line_abs = [restore_map[stripped_start + offset] for offset in range(len(line))]
                    normalized = normalize_bangla_with_offsets(line)
                    buffer.append(
                        _Line(
                            text=normalized.text,
                            page=page.page_number,
                            segments=_segments_from_offsets(normalized, line_abs),
                        )
                    )
                    buffer_tokens += _token_count(normalized.text)
                    if buffer_tokens >= target_tokens + _FLUSH_HEADROOM:
                        flush()
            line_start += len(raw_line) + 1
    flush()
    return chunks


def _original_text(spans: list[SourceSpan], pages: list[PageText]) -> str:
    """Exact source slice of a chunk: the extracted text its spans cover."""
    page_text = {page.page_number: page.text for page in pages}
    parts: list[str] = []
    current_page: int | None = None
    for span in spans:
        text = page_text.get(span.page, "")
        if current_page is not None and span.page != current_page:
            parts.append("\n")
        parts.append(text[span.page_start : span.page_end])
        current_page = span.page
    return "".join(parts)
