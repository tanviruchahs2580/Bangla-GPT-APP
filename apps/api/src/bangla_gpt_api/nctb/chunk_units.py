"""Table, formula and number-row recognition for the NCTB chunker (A2-04e).

Extracted from ``chunking.py`` for cohesion: these predicates decide a block's
*kind* (data-table row vs formula unit vs prose row), which the chunker then
never splits mid-unit. Thresholds are pinned by
``tests/test_a1_chunk_boundaries.py`` and ``test_a5_nctb_structure_metadata.py``.
"""

from __future__ import annotations

import re

# The line-break restoration is a text-normalisation step that needs the
# heading patterns; importing them (not duplicating) keeps one definition.
from bangla_gpt_api.nctb.chunk_headings import (
    _COLON_HEADING_BREAK,
    _HEADING_BREAK,
    _SECTION_BREAK,
)

TABLE_ROW_MIN_WIDE_GAPS = 2
NUMBER_ROW_MIN_TOKENS = 5
NUMBER_ROW_MAX_TOKENS = 14
NUMBER_ROW_MIN_RATIO = 0.55
FORMULA_MIN_OPERATORS = 2

# ── faithful table / formula representation (A2-04e) ──────────────────────
# The extractor preserves a table row when the PDF carries column geometry:
# two or more runs of 2+ spaces between cells (measured on the corpus: 328 of
# 4970 real lines; the curriculum chapter tables and running headers). Such a
# line is re-joined with " | " so the row stays tabular — cells in order, still
# separable — instead of collapsing into a prose sentence. Rows are kept on
# their own lines inside a chunk and are never split mid-row.
_COLUMN_GAP = re.compile(r"\s{2,}")


#: prose in the English volume uses exactly 2-space gaps between words — 41 of
#: the 57 multi-gap lines — so requiring two gaps of 4+ spaces keeps those out
#: and leaves the real assessment rows, e.g. "Reading || 40").
_WIDE_COLUMN_GAP = re.compile(r" {4,}")


#: Detected by token shape because the extractor gives it single spaces.
_NUMBER_TOKEN = re.compile(r"^[\d\u09e6-\u09ef.,%()\-]+$")


TABLE_CELL_SEPARATOR = " | "


TABLE_ROW_SEPARATOR = "\n"


#: comparison/root/power signs). A line whose non-space characters are mostly
#: these is a formula, not prose: it is kept as one unit, spaced as extracted.
_FORMULA_CHARS = frozenset(
    "0123456789=+-×÷·∗√∑∫≤≥≠≈±°^%<>/\\|"
    "\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef"
    "\u00d7\u00f7\u2212\u2211\u222b\u2264\u2265\u2260\u2248\u00b1\u00b2\u00b3\u221a"
)


#: table row (see _is_number_row), not a formula.
_FORMULA_OPERATORS = frozenset("=+-×÷−√²³^%<>/¼½¾∗")


#: of them as letters (so it is the dominant content), and 2+ operators.
FORMULA_MIN_CHARS = 6


def _is_number_row(line: str) -> bool:
    """True for a marks/weight table row (tokens are mostly numbers)."""
    tokens = line.split()
    if not NUMBER_ROW_MIN_TOKENS <= len(tokens) <= NUMBER_ROW_MAX_TOKENS:
        return False
    numeric = sum(1 for token in tokens if _NUMBER_TOKEN.match(token))
    return numeric >= NUMBER_ROW_MIN_TOKENS and numeric / len(tokens) >= NUMBER_ROW_MIN_RATIO


def _is_table_row(line: str) -> bool:
    """True when the extracted line is tabular: 2+ wide column gaps (>= 3
    cells) or a number row."""
    if len(_WIDE_COLUMN_GAP.findall(line)) >= TABLE_ROW_MIN_WIDE_GAPS:
        return True
    return _is_number_row(line)


def _format_table_row(line: str) -> str:
    """Re-join a table row's cells with ``" | "`` instead of spaces."""
    cells = [cell.strip() for cell in _COLUMN_GAP.split(line.strip())]
    cells = [cell for cell in cells if cell]
    if len(cells) >= 3:
        return TABLE_CELL_SEPARATOR.join(cells)
    # a number row has single-space cells: the tokens ARE the cells
    return TABLE_CELL_SEPARATOR.join(line.split())


def _symbol_counts(compact: list[str]) -> tuple[int, int, int]:
    """Count (formula chars, letters, operator signs) in a line's non-space chars."""
    formula = sum(1 for char in compact if char in _FORMULA_CHARS)
    letters = sum(1 for char in compact if char.isalpha())
    operators = sum(1 for char in compact if char in _FORMULA_OPERATORS)
    return formula, letters, operators


def _is_formula_line(line: str) -> bool:
    """True when a line is symbol-dominant: a formula or phonetic notation.

    Requires formula characters to dominate the line, at least two operator
    signs (so a marks row is excluded) and that the line is not a number row.
    """
    compact = [char for char in line if not char.isspace()]
    if not compact:
        return False
    formula, letters, operators = _symbol_counts(compact)
    dominant = formula >= FORMULA_MIN_CHARS and formula >= letters
    signed = operators >= FORMULA_MIN_OPERATORS and not _is_number_row(line)
    return dominant and signed


def _restore_line_breaks(text: str) -> str:
    text = _HEADING_BREAK.sub("\n", text)
    text = _COLON_HEADING_BREAK.sub("\n", text)
    return _SECTION_BREAK.sub("\n", text)
