"""One Bangla normalizer for ingestion, indexing and query analysis.

The corpus used to be ingested with NFC and queried with NFKC (F-133): a
document could be indexed in a form no query ever reproduces, and the two
policies were only comparable by hand. This module owns the single
definition; ``nctb.normalize`` (ingestion), ``retrieval.hybrid.tokenize``
(indexing/query analysis) and the tutor's query boundary all fold through it.

Whitespace is the one deliberate difference between the two callers: the
ingest form collapses runs and strips the edges because chunk text is stored
and hashed; the query form must not rewrite the student's own text, so
:func:`normalize_nfkc` keeps interior spacing and the ingest form applies
:func:`collapse_whitespace` on top of it.

:func:`normalize_with_offsets` additionally returns the map from normalized
characters back into the original text, which is what lets a highlight or a
citation point into the source page instead of a normalized copy.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

#: ZWSP, ZWNJ, ZWJ, BOM. Invisible characters would otherwise defeat the
#: plain-substring safety, injection and citation regexes.
ZERO_WIDTH_CHARS = frozenset("\u200b\u200c\u200d\ufeff")

BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def strip_zero_width(text: str) -> str:
    """Drop ZWSP/ZWJ/ZWNJ/BOM without touching anything else."""
    return "".join(char for char in text if char not in ZERO_WIDTH_CHARS)


def normalize_nfkc(text: str) -> str:
    """The shared normalization: NFKC plus zero-width removal.

    NFKC (not NFC) is the form both sides use: it folds the mobile-keyboard
    compatibility variants and precomposed/decomposed Bangla the query side
    always folded anyway.
    """
    return strip_zero_width(unicodedata.normalize("NFKC", text))


def collapse_whitespace(text: str) -> str:
    """Collapse every whitespace run to one space and strip the edges."""
    return " ".join(text.split())


@dataclass(frozen=True)
class NormalizedText:
    """Normalized text plus its map back into the original string.

    ``offsets[i]`` is the half-open ``(start, end)`` range in the original
    text that produced ``text[i]``; ranges are non-decreasing. A collapsed
    whitespace run maps its single space to the whole run, so
    :meth:`map_span` returns the original run. ``cluster_starts`` lists the
    output index at which each normalization cluster begins, which is the
    granularity at which the map is exact: a cluster's source range and its
    produced characters correspond as a unit.
    """

    text: str
    offsets: tuple[tuple[int, int], ...]
    cluster_starts: tuple[int, ...] = ()

    def map_span(self, start: int, end: int) -> tuple[int, int] | None:
        """Original range for normalized ``text[start:end]``; None if empty."""
        if start >= end or not self.offsets:
            return None
        start = max(start, 0)
        end = min(end, len(self.offsets))
        if start >= end:
            return None
        return self.offsets[start][0], self.offsets[end - 1][1]


def _is_combining(char: str) -> bool:
    return unicodedata.category(char).startswith("M")


def normalize_with_offsets(text: str, *, ascii_digits: bool = False) -> NormalizedText:
    """Normalize and keep the map from output characters to the input.

    NFKC is applied per *cluster* (a base character plus its combining
    marks). Canonical composition cannot cross a cluster boundary — a
    combining mark always composes with its own base — so concatenating the
    per-cluster results is byte-identical to normalizing the whole string;
    ``test_w2_corpus_normalize`` asserts exactly that on mixed fixtures.

    A cluster's input range is split across its output characters in
    proportion, so a length-preserving cluster maps 1:1 while a
    compatibility decomposition (one input character becoming several, e.g.
    ``ড়`` -> ``ড`` + nukta) still points every output character at the same
    source character.
    """
    out: list[str] = []
    offsets: list[tuple[int, int]] = []
    cluster_starts: list[int] = []
    index = 0
    total = len(text)
    pending_space: tuple[int, int] | None = None
    while index < total:
        char = text[index]
        if char.isspace():
            run_end = index
            while run_end < total and text[run_end].isspace():
                run_end += 1
            if out:
                pending_space = (index, run_end)
            index = run_end
            continue
        if char in ZERO_WIDTH_CHARS:
            index += 1
            continue
        cluster_end = index + 1
        while cluster_end < total and _is_combining(text[cluster_end]):
            cluster_end += 1
        cluster = unicodedata.normalize("NFKC", text[index:cluster_end])
        if pending_space is not None and out:
            out.append(" ")
            offsets.append(pending_space)
            cluster_starts.append(len(out) - 1)
        pending_space = None
        cluster_starts.append(len(out))
        cluster_len = cluster_end - index
        produced = len(cluster)
        for position, char_out in enumerate(cluster):
            start = index + (position * cluster_len) // produced
            end = index + ((position + 1) * cluster_len) // produced
            out.append(char_out)
            offsets.append((start, max(end, start + 1)))
        index = cluster_end
    if ascii_digits:
        out = [char.translate(BENGALI_DIGITS) for char in out]
    return NormalizedText(
        text="".join(out),
        offsets=tuple(offsets),
        cluster_starts=tuple(cluster_starts),
    )
