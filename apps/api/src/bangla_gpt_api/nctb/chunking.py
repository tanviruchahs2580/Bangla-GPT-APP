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

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Any

from bangla_gpt_api.nctb.chunk_headings import (  # noqa: F401
    _CELL_MARKERS,  # noqa: F401
    _COLON_HEADING_BREAK,  # noqa: F401
    _HEADING_BREAK,  # noqa: F401
    _LABEL_TRIM,  # noqa: F401
    _ORDINAL_ALT,  # noqa: F401
    _ORDINAL_REPAIRS,  # noqa: F401
    _PROSE_CONTINUATIONS,  # noqa: F401
    _PROSE_TITLE_WORDS,  # noqa: F401
    _SECTION_BREAK,  # noqa: F401
    _TITLE_CUT,  # noqa: F401
    CHAPTER_ORDINALS,  # noqa: F401
    CHAPTER_PATTERNS,  # noqa: F401
    MAX_CHAPTER_LABEL_CHARS,  # noqa: F401
    MAX_CHAPTER_TITLE_WORDS,  # noqa: F401
    SECTION_HINTS,  # noqa: F401
    _clean_chapter_title,  # noqa: F401
    _is_chapter_heading,
    _truncate_at_marker,  # noqa: F401
)
from bangla_gpt_api.nctb.chunk_packing import (  # noqa: F401
    _SENTENCE_SPLIT,  # noqa: F401
    _buffer_units,
    _join_units,
    _pack_units,
    _Unit,
    pack_sentences,
    split_sentences,
)
from bangla_gpt_api.nctb.chunk_sizing import (  # noqa: F401
    DEFAULT_OVERLAP_WORDS,  # noqa: F401
    FLUSH_AHEAD_RATIO,  # noqa: F401
    MAX_TOKENS,
    MAX_WORDS,  # noqa: F401
    MIN_TOKENS,
    MIN_WORDS,
    TARGET_TOKENS,
    TARGET_WORDS,  # noqa: F401
    TOKENS_PER_WORD_MEASURED,  # noqa: F401
    _resolve_sizing,
    _Sizing,
    _token_window,  # noqa: F401
    _word_window,  # noqa: F401
)
from bangla_gpt_api.nctb.chunk_units import (  # noqa: F401
    _COLUMN_GAP,  # noqa: F401
    _FORMULA_CHARS,  # noqa: F401
    _FORMULA_OPERATORS,  # noqa: F401
    _NUMBER_TOKEN,  # noqa: F401
    _WIDE_COLUMN_GAP,  # noqa: F401
    FORMULA_MIN_CHARS,  # noqa: F401
    FORMULA_MIN_OPERATORS,  # noqa: F401
    NUMBER_ROW_MAX_TOKENS,  # noqa: F401
    NUMBER_ROW_MIN_RATIO,  # noqa: F401
    NUMBER_ROW_MIN_TOKENS,  # noqa: F401
    TABLE_CELL_SEPARATOR,
    TABLE_ROW_MIN_WIDE_GAPS,  # noqa: F401
    TABLE_ROW_SEPARATOR,  # noqa: F401
    _format_table_row,
    _is_formula_line,
    _is_number_row,  # noqa: F401
    _is_table_row,
    _restore_line_breaks,
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
    parent = _union_cross_source_pairs(prepared, threshold=threshold, min_chars=min_chars)
    groups: dict[int, list[tuple[str, str]]] = {}
    for i, (chunk_id, source_id, _len, _grams) in enumerate(prepared):
        groups.setdefault(_find_root(parent, i), []).append((source_id, chunk_id))
    return [sorted(members) for members in groups.values() if len(members) >= 2]


def _find_root(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _union_cross_source_pairs(
    prepared: list[tuple[str, str, int, frozenset[str]]],
    *,
    threshold: float,
    min_chars: int,
) -> list[int]:
    """Union-find pass over the cross-source trigram-Jaccard pairs."""
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
            if source_i == source_j or not grams_i or not grams_j:
                continue
            if min(len_i, len_j) < min_chars:
                continue  # short headings legitimately repeat; too little content
            union = len(grams_i | grams_j)
            if union and len(grams_i & grams_j) / union >= threshold:
                ri, rj = _find(i), _find(j)
                if ri != rj:
                    parent[ri] = rj
    return parent


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
