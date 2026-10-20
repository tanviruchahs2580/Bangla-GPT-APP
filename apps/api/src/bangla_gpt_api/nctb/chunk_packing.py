"""Sentence packing and preserved-unit packing for the NCTB chunker.

Extracted from ``chunking.py`` for cohesion and file size. Two layers live
here:

* :func:`pack_sentences` — the sentence discipline: the size target is met by
  packing whole sentences (Bangla danda ``।``, ``?``, ``!``), an over-long
  sentence is the only case split on word/token boundaries, and a merge that
  would overshoot the maximum is split rather than truncated (the
  pre-2026-10-18 implementation dropped the overflow tail silently);
* :func:`_buffer_units` / :func:`_pack_units` — the faithful-representation
  layer (A2-04e): buffer lines are classified *before* whitespace collapsing,
  table rows are re-joined with ``" | "``, and a preserved row or formula line
  is an indivisible atom that stays on its own line and is never split by the
  size target.

Everything here is re-exported from ``bangla_gpt_api.nctb.chunking``, which
stays the module the pipeline, the scripts and the tests import from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise

from bangla_gpt_api.nctb.chunk_sizing import (
    DEFAULT_OVERLAP_WORDS,
    MAX_WORDS,
    MIN_WORDS,
    _resolve_sizing,
    _Sizing,
)
from bangla_gpt_api.nctb.chunk_units import (
    TABLE_ROW_SEPARATOR,
    _format_table_row,
    _is_formula_line,
    _is_table_row,
)
from bangla_gpt_api.nctb.normalize import normalize_bangla
from bangla_gpt_api.services.context import TokenCounter

# Sentence boundary: Bangla danda / question mark / exclamation mark followed
# by whitespace. ASCII '.' is deliberately NOT a boundary (the curriculum
# documents carry English abbreviations such as "M.Sc." inside Bangla prose).
_SENTENCE_SPLIT = re.compile(r"(?<=[।?!])\s+")


def split_sentences(text: str) -> list[str]:
    """Split on Bangla danda/``?``/``!``; whitespace-collapsed input expected."""
    return [part for part in (p.strip() for p in _SENTENCE_SPLIT.split(text)) if part]


def _sentence_units(text: str, sizing: _Sizing) -> list[str]:
    """Sentences of ``text``; an over-long one is windowed on word/token boundaries."""
    units: list[str] = []
    for sentence in split_sentences(text):
        if sizing.measure(sentence) > sizing.maximum:
            units.extend(sizing.window(sentence, sizing.target))
        else:
            units.append(sentence)
    return units


def _fill_pieces(sentences: list[str], sizing: _Sizing, overlap_words: int) -> list[str]:
    """Accumulate sentences into pieces bounded by the size target.

    A piece is closed before a sentence that would overshoot the target, once
    the piece can stand alone (otherwise the sentence is admitted, keeping the
    historical "short blocks are never dropped" behaviour); ``overlap_words``
    repeats that many trailing words at the start of the next piece.
    """
    pieces: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        current_text = " ".join(current)
        # The prospective piece is measured WITH its joining space: token
        # counts are not additive (the separator is inside the measured text),
        # so adding the sentence's own measure would admit pieces a character
        # counter then reports as over target. Word counts are additive, so
        # the historical word sizing is unchanged.
        if (
            current
            and sizing.measure(f"{current_text} {sentence}") > sizing.target
            and not sizing.below_minimum(current_text)
        ):
            pieces.append(current_text)
            current = current[-overlap_words:] if overlap_words > 0 else []
        current.extend(sentence.split(" "))
    if current:
        current_text = " ".join(current)
        if pieces and sizing.below_minimum(current_text):
            pieces[-1] = f"{pieces[-1]} {current_text}"
        else:
            pieces.append(current_text)
    return pieces


def _bounded(pieces: list[str], sizing: _Sizing) -> list[str]:
    """Split any piece still over the maximum — never truncate it.

    The split lands on the size TARGET, not on the maximum: a piece reaches
    this path only when a merge pushed it over the maximum, and splitting it
    at the target keeps the resulting pieces comparable to every other piece
    of the build (the wave-5 ablation's word-sized rows reproduce exactly
    under this rule, 1 523 served chunks at 220 words, and the recorded
    per-source token fingerprint is identical either way).
    """
    bounded: list[str] = []
    for piece in pieces:
        if sizing.measure(piece) > sizing.maximum:
            bounded.extend(sizing.window(piece, sizing.target))
        else:
            bounded.append(piece)
    return bounded


def pack_sentences(
    text: str,
    *,
    target_tokens: int | None = None,
    min_tokens: int | None = None,
    max_tokens: int | None = None,
    target_words: int | None = None,
    min_words: int = MIN_WORDS,
    max_words: int = MAX_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
    counter: TokenCounter | None = None,
    sizing: _Sizing | None = None,
) -> list[str]:
    """Pack whole sentences into pieces of the configured size (A3-01).

    * a sentence longer than the maximum is split on word boundaries
      (nothing left to respect inside it);
    * a trailing piece below the minimum merges into the previous piece;
    * ``overlap_words`` repeats that many trailing words of each piece at
      the start of the next (0 keeps the historical no-overlap behaviour);
    * pieces larger than the maximum are split, never truncated.

    Sizing defaults to tokens measured with the configured
    ``services.context.TokenCounter``; passing ``target_words`` selects the
    historical word sizing (the documented fallback). ``sizing`` takes a
    resolved :class:`_Sizing` (the chunker's per-call resolution).
    """
    resolved = sizing or _resolve_sizing(
        target_tokens=target_tokens,
        min_tokens=min_tokens,
        max_tokens=max_tokens,
        target_words=target_words,
        min_words=min_words,
        max_words=max_words,
        counter=counter,
    )
    return _bounded(
        _fill_pieces(_sentence_units(text, resolved), resolved, overlap_words), resolved
    )


@dataclass(frozen=True)
class _Unit:
    """One indivisible piece of a flush buffer (A2-04e).

    ``kind`` is ``"prose"`` (packable at sentence boundaries), ``"table"`` (a
    preserved row) or ``"formula"`` (a symbol-dominant line); the latter two
    are atoms — never split, always kept on their own line.
    """

    kind: str
    text: str


def _buffer_units(lines: list[str]) -> list[_Unit]:
    """Classify buffer lines into prose runs, table rows and formula lines.

    Classification reads the *extracted* line, before whitespace collapsing:
    the column geometry that makes a row tabular (2+ runs of 4+ spaces) only
    exists there. Consecutive prose lines form one run so sentences pack
    across line breaks exactly as they did before units existed.
    """
    units: list[_Unit] = []
    prose: list[str] = []

    def flush_prose() -> None:
        if prose:
            units.append(_Unit("prose", normalize_bangla(" ".join(prose))))
            prose.clear()

    for line in lines:
        if _is_formula_line(line):
            flush_prose()
            units.append(_Unit("formula", normalize_bangla(line)))
        elif _is_table_row(line):
            flush_prose()
            units.append(_Unit("table", normalize_bangla(_format_table_row(line))))
        else:
            prose.append(line)
    flush_prose()
    return units


def _join_units(units: list[_Unit]) -> str:
    """Join atoms into chunk text: prose flows, preserved units keep a line."""
    parts = [units[0].text]
    for previous, unit in pairwise(units):
        prose_pair = unit.kind == "prose" and previous.kind == "prose"
        parts.append(" " if prose_pair else TABLE_ROW_SEPARATOR)
        parts.append(unit.text)
    return "".join(parts).strip()


def _pack_units(
    units: list[_Unit],
    sizing: _Sizing,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
) -> list[str]:
    """Pack units into chunk texts; a preserved unit is never split (A2-04e).

    Prose runs are first packed into sentence-aligned pieces; table rows and
    formula lines enter as single atoms. Atoms are joined while the measured
    size stays within the target, so a row or equation survives intact even
    when it alone exceeds it. ``overlap_words`` is threaded to the sentence
    packer (the chunk-size ablation's overlap configurations) and never
    applies to a preserved unit, which is carried whole.
    """
    atoms: list[_Unit] = []
    for unit in units:
        if unit.kind == "prose":
            atoms.extend(
                _Unit("prose", piece)
                for piece in pack_sentences(unit.text, sizing=sizing, overlap_words=overlap_words)
            )
        else:
            atoms.append(unit)

    pieces: list[str] = []
    current: list[_Unit] = []
    size = 0
    for atom in atoms:
        measured = sizing.measure(atom.text)
        if current and size + measured > sizing.target:
            pieces.append(_join_units(current))
            current, size = [], 0
        current.append(atom)
        size += measured
    if current:
        pieces.append(_join_units(current))
    return pieces
