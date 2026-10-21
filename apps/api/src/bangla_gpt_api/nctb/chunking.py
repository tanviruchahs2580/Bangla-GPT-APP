"""Structure-aware semantic chunking of extracted NCTB pages.

Hierarchy implemented (master §16/§17):
    Chapter (parent unit, detected from Bangla headings)
      └── Section-sized child chunks (retrieval units)

Boundaries prefer paragraph/heading lines and then *sentences*: the size
target is met by packing whole sentences (Bangla danda ``।``, ``?``, ``!``)
up to the target, never by cutting a sentence in half. A sentence longer than
the maximum is the only case split on word boundaries (there is no punctuation
left to respect) and a merge that would overshoot the maximum is split rather
than truncated — the earlier implementation silently dropped the overflow
tail. Chapter/section/page provenance is preserved on every chunk.

Chunk size is measured in TOKENS (A3-01) with the configured
``services.context.TokenCounter`` — the calibrated heuristic upper bound by
default, the vendor counter when one is registered. The token defaults are
derived from the historical word defaults (see TARGET_TOKENS) so the unit
change is not a silent size change; word sizing remains the documented
fallback, selected by passing ``target_words``.

Tables and formulas keep a faithful representation (A2-04e): a line with
column geometry stays a pipe-separated row on its own line, a formula-dominant
line stays one spaced unit, and neither is ever split mid-unit. The quality
report carries both size histograms and the preserved-unit counts of every
build, so a unit change is visible in the artifact, not only in this file.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from bangla_gpt_api.nctb.chunk_headings import (
    # noqa: F401
    _CELL_MARKERS as _CELL_MARKERS,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _COLON_HEADING_BREAK as _COLON_HEADING_BREAK,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _HEADING_BREAK as _HEADING_BREAK,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _LABEL_TRIM as _LABEL_TRIM,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _ORDINAL_ALT as _ORDINAL_ALT,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _ORDINAL_REPAIRS as _ORDINAL_REPAIRS,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _PROSE_CONTINUATIONS as _PROSE_CONTINUATIONS,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _PROSE_TITLE_WORDS as _PROSE_TITLE_WORDS,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _SECTION_BREAK as _SECTION_BREAK,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _TITLE_CUT as _TITLE_CUT,
)
from bangla_gpt_api.nctb.chunk_headings import (
    CHAPTER_ORDINALS as CHAPTER_ORDINALS,
)
from bangla_gpt_api.nctb.chunk_headings import (
    CHAPTER_PATTERNS as CHAPTER_PATTERNS,
)
from bangla_gpt_api.nctb.chunk_headings import (
    MAX_CHAPTER_LABEL_CHARS as MAX_CHAPTER_LABEL_CHARS,
)
from bangla_gpt_api.nctb.chunk_headings import (
    MAX_CHAPTER_TITLE_WORDS as MAX_CHAPTER_TITLE_WORDS,
)
from bangla_gpt_api.nctb.chunk_headings import (
    SECTION_HINTS as SECTION_HINTS,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _clean_chapter_title as _clean_chapter_title,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _is_chapter_heading as _is_chapter_heading,
)
from bangla_gpt_api.nctb.chunk_headings import (
    _truncate_at_marker as _truncate_at_marker,
)
from bangla_gpt_api.nctb.chunk_packing import (
    # noqa: F401
    _SENTENCE_SPLIT as _SENTENCE_SPLIT,
)
from bangla_gpt_api.nctb.chunk_packing import (
    _buffer_units as _buffer_units,
)
from bangla_gpt_api.nctb.chunk_packing import (
    _join_units as _join_units,
)
from bangla_gpt_api.nctb.chunk_packing import (
    _pack_units as _pack_units,
)
from bangla_gpt_api.nctb.chunk_packing import (
    _Unit as _Unit,
)
from bangla_gpt_api.nctb.chunk_packing import (
    pack_sentences as pack_sentences,
)
from bangla_gpt_api.nctb.chunk_packing import (
    split_sentences as split_sentences,
)
from bangla_gpt_api.nctb.chunk_records import (
    RawChunk as RawChunk,
)
from bangla_gpt_api.nctb.chunk_records import (
    _find_root as _find_root,
)
from bangla_gpt_api.nctb.chunk_records import (
    _stable_id as _stable_id,
)
from bangla_gpt_api.nctb.chunk_records import (
    _text_fingerprint as _text_fingerprint,
)
from bangla_gpt_api.nctb.chunk_records import (
    _union_cross_source_pairs as _union_cross_source_pairs,
)
from bangla_gpt_api.nctb.chunk_records import (
    dedupe_chunks as dedupe_chunks,
)
from bangla_gpt_api.nctb.chunk_records import (
    near_duplicate_groups as near_duplicate_groups,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    # noqa: F401
    DEFAULT_OVERLAP_WORDS as DEFAULT_OVERLAP_WORDS,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    FLUSH_AHEAD_RATIO as FLUSH_AHEAD_RATIO,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    MAX_TOKENS as MAX_TOKENS,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    MAX_WORDS as MAX_WORDS,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    MIN_TOKENS as MIN_TOKENS,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    MIN_WORDS as MIN_WORDS,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    TARGET_TOKENS as TARGET_TOKENS,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    TARGET_WORDS as TARGET_WORDS,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    TOKENS_PER_WORD_MEASURED as TOKENS_PER_WORD_MEASURED,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    _resolve_sizing as _resolve_sizing,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    _Sizing as _Sizing,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    _token_window as _token_window,
)
from bangla_gpt_api.nctb.chunk_sizing import (
    _word_window as _word_window,
)
from bangla_gpt_api.nctb.chunk_units import (
    # noqa: F401
    _COLUMN_GAP as _COLUMN_GAP,
)
from bangla_gpt_api.nctb.chunk_units import (
    _FORMULA_CHARS as _FORMULA_CHARS,
)
from bangla_gpt_api.nctb.chunk_units import (
    _FORMULA_OPERATORS as _FORMULA_OPERATORS,
)
from bangla_gpt_api.nctb.chunk_units import (
    _NUMBER_TOKEN as _NUMBER_TOKEN,
)
from bangla_gpt_api.nctb.chunk_units import (
    _WIDE_COLUMN_GAP as _WIDE_COLUMN_GAP,
)
from bangla_gpt_api.nctb.chunk_units import (
    FORMULA_MIN_CHARS as FORMULA_MIN_CHARS,
)
from bangla_gpt_api.nctb.chunk_units import (
    FORMULA_MIN_OPERATORS as FORMULA_MIN_OPERATORS,
)
from bangla_gpt_api.nctb.chunk_units import (
    NUMBER_ROW_MAX_TOKENS as NUMBER_ROW_MAX_TOKENS,
)
from bangla_gpt_api.nctb.chunk_units import (
    NUMBER_ROW_MIN_RATIO as NUMBER_ROW_MIN_RATIO,
)
from bangla_gpt_api.nctb.chunk_units import (
    NUMBER_ROW_MIN_TOKENS as NUMBER_ROW_MIN_TOKENS,
)
from bangla_gpt_api.nctb.chunk_units import (
    TABLE_CELL_SEPARATOR as TABLE_CELL_SEPARATOR,
)
from bangla_gpt_api.nctb.chunk_units import (
    TABLE_ROW_MIN_WIDE_GAPS as TABLE_ROW_MIN_WIDE_GAPS,
)
from bangla_gpt_api.nctb.chunk_units import (
    TABLE_ROW_SEPARATOR as TABLE_ROW_SEPARATOR,
)
from bangla_gpt_api.nctb.chunk_units import (
    _format_table_row as _format_table_row,
)
from bangla_gpt_api.nctb.chunk_units import (
    _is_formula_line as _is_formula_line,
)
from bangla_gpt_api.nctb.chunk_units import (
    _is_number_row as _is_number_row,
)
from bangla_gpt_api.nctb.chunk_units import (
    _is_table_row as _is_table_row,
)
from bangla_gpt_api.nctb.chunk_units import (
    _restore_line_breaks as _restore_line_breaks,
)
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.nctb.normalize import normalize_bangla
from bangla_gpt_api.services.context import TokenCounter, token_counter

# Sentence packing and preserved-unit packing live in ``chunk_packing``; the
# ``_SENTENCE_SPLIT`` / ``split_sentences`` / ``pack_sentences`` / ``_Unit`` /
# ``_buffer_units`` / ``_join_units`` / ``_pack_units`` names above are
# re-exports, so this module stays the one import path for the pipeline.

# Numbered curriculum headings in the schools' curriculum volumes
# ("৪.১ অবস্থা বিশ্লেষণ", "৬.৩ সাধারণ শিক্ষা ধারার …"), unlike textbook
# chapters. They are section-level boundaries, not chapters.
_NUMBERED_HEADING = re.compile(r"^[০-৯0-9]{1,2}(?:\.[০-৯0-9]{1,2})*[.)]?\s+\S")


def _section_label(line: str, *, can_stand_alone: bool) -> str | None:
    """Section marker for a line, or None (A2-04a).

    A hint word (অনুশীলনী…) makes a short line a section. A numbered
    curriculum heading ("৫.২ পরিমাপ ও একক") is only a section once the current
    block can stand alone, so numbered *lists* inside prose never fragment
    into sub-minimum fragments.
    """
    normalized = normalize_bangla(line)
    if any(hint in normalized for hint in SECTION_HINTS) and len(normalized) < 60:
        return normalized[:80]
    if _NUMBERED_HEADING.match(normalized) and can_stand_alone:
        return normalized[:80]
    return None


class _ChunkBuffer:
    """Accumulator turning page lines into chapter/section-aware chunks.

    One instance per :func:`chunk_pages` call. Holding the buffer state and
    the flush policy here keeps the page loop (and this module's complexity)
    small: the loop feeds lines, the buffer decides when a block closes.
    """

    def __init__(
        self,
        *,
        source_id: str,
        sizing: _Sizing,
        overlap_words: int = DEFAULT_OVERLAP_WORDS,
    ) -> None:
        self.source_id = source_id
        self.sizing = sizing
        self.overlap_words = overlap_words
        self.chunks: list[RawChunk] = []
        self.short_blocks = 0
        self.table_rows = 0
        self.formula_units = 0
        self._lines: list[str] = []
        self._pages: set[int] = set()
        self._chapter = ""
        self._chapter_seq = 0
        self._section = ""
        self._buffer_section = ""

    @property
    def _text(self) -> str:
        """The buffered block as it would be normalized for indexing."""
        return normalize_bangla(" ".join(self._lines))

    def can_stand_alone(self) -> bool:
        """True when the buffered block is big enough to close at a heading."""
        return not self.sizing.below_minimum(self._text)

    def add_line(self, line: str, page_number: int) -> None:
        """Buffer one content line, remembering the section it started in."""
        if not self._lines:
            self._buffer_section = self._section
        self._lines.append(line)
        self._pages.add(page_number)

    def start_chapter(self, label: str) -> None:
        """A chapter heading closes the block and re-parents what follows."""
        self.flush()
        self._chapter_seq += 1
        self._chapter = label
        self._section = ""

    def start_section(self, label: str) -> None:
        """A section marker closes the block forward, then labels what follows."""
        self.flush(merge_forward=True)
        if not self._lines:
            self._section = label

    def flush_if_ahead(self) -> None:
        """Close the block early once it overshoots the slack budget."""
        if self._lines and self.sizing.measure(self._text) >= self.sizing.flush_ahead:
            self.flush()

    def flush(self, *, merge_forward: bool = False) -> None:
        """Emit the buffer as chunks; a sub-minimum block is never dropped.

        ``merge_forward`` holds a too-small block for the next one (used at
        section markers, where the following block carries the heading's
        text); otherwise it merges into the previous chunk, and only a
        too-small FIRST block — with nothing to merge into — is discarded.
        """
        if not self._lines:
            return
        if self.sizing.below_minimum(self._text):
            self._merge_small_block(merge_forward=merge_forward)
            return
        units = _buffer_units(self._lines)
        self._count_preserved(units)
        pages = self._pages
        for piece in _pack_units(units, self.sizing, self.overlap_words):
            self.chunks.append(self._make_chunk(piece, pages))
        self._clear()

    def write_stats(self, stats: dict[str, Any]) -> None:
        """Report the build's sizing unit, histograms and preserved units."""
        counter = self.sizing.counter or token_counter()
        stats["short_blocks_merged"] = self.short_blocks
        stats["chunk_word_lengths"] = [len(chunk.text.split(" ")) for chunk in self.chunks]
        stats["chunk_token_lengths"] = [counter.count(chunk.text) for chunk in self.chunks]
        stats["sizing_unit"] = self.sizing.unit
        stats["token_counter"] = counter.name
        stats["table_rows_preserved"] = self.table_rows
        stats["formula_units_preserved"] = self.formula_units

    def _make_chunk(self, piece: str, pages: set[int]) -> RawChunk:
        return RawChunk(
            chunk_id=_stable_id(self.source_id, "chunk", self._chapter_seq, min(pages), piece),
            parent_id=(
                _stable_id(self.source_id, "chapter", self._chapter_seq, self._chapter)
                if self._chapter
                else None
            ),
            text=piece,
            original_text=" ".join(self._lines)[: len(piece) * 2],
            chapter=self._chapter,
            page_start=min(pages),
            page_end=max(pages),
            section=self._buffer_section,
        )

    def _merge_small_block(self, *, merge_forward: bool) -> None:
        """Hold a sub-minimum block forward, or merge it into the last chunk."""
        self.short_blocks += 1
        if merge_forward:
            return
        if not self.chunks:
            self._clear()
            return
        units = _buffer_units(self._lines)
        self._count_preserved(units)
        tail = _join_units(units)
        separator = " " if units[0].kind == "prose" else "\n"
        self.chunks[-1] = replace(
            self.chunks[-1],
            text=f"{self.chunks[-1].text}{separator}{tail}".strip(),
            page_end=max(self.chunks[-1].page_end, max(self._pages)),
        )
        self._clear()

    def _count_preserved(self, units: list[_Unit]) -> None:
        self.table_rows += sum(1 for unit in units if unit.kind == "table")
        self.formula_units += sum(1 for unit in units if unit.kind == "formula")

    def _clear(self) -> None:
        self._lines = []
        self._pages = set()
        self._buffer_section = ""


def _add_line(buffer: _ChunkBuffer, line: str, page_number: int) -> None:
    """Feed one page line: chapter heading, section marker or content."""
    stripped = line.strip()
    if not stripped:
        return
    heading = _is_chapter_heading(stripped)
    if heading is not None:
        buffer.start_chapter(heading)
        return
    label = _section_label(stripped, can_stand_alone=buffer.can_stand_alone())
    if label is not None:
        buffer.start_section(label)
    buffer.add_line(stripped, page_number)


def chunk_pages(
    pages: list[PageText],
    *,
    source_id: str,
    target_tokens: int | None = None,
    min_tokens: int | None = None,
    max_tokens: int | None = None,
    target_words: int | None = None,
    min_words: int = MIN_WORDS,
    max_words: int = MAX_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
    counter: TokenCounter | None = None,
    stats: dict[str, Any] | None = None,
) -> list[RawChunk]:
    """Build chapter-parented, section-aware chunks with page provenance.

    Sizing is token-based by default (A3-01); passing ``target_words`` keeps
    the historical word sizing, the config the chunk-size ablation's baseline
    rows use. ``stats`` (optional, additive) receives the sizing unit and
    counter, the word/token length histograms, the merged-sub-minimum-block
    count and the preserved table/formula unit counts, so the corpus report
    can carry them without a second pass over the chunks.
    """
    sizing = _resolve_sizing(
        target_tokens=target_tokens,
        min_tokens=min_tokens,
        max_tokens=max_tokens,
        target_words=target_words,
        min_words=min_words,
        max_words=max_words,
        counter=counter,
    )
    buffer = _ChunkBuffer(source_id=source_id, sizing=sizing, overlap_words=overlap_words)
    for page in pages:
        if not page.usable:
            continue
        for line in _restore_line_breaks(page.text).splitlines():
            _add_line(buffer, line, page.page_number)
            buffer.flush_if_ahead()
    buffer.flush()
    if stats is not None:
        buffer.write_stats(stats)
    return buffer.chunks
