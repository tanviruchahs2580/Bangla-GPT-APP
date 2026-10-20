"""Chunk records and dedupe for the NCTB pipeline (A2-05).

Split out of ``chunking.py`` (C-03): the record shape every artifact row is
written from, its content hashes, and the two duplicate passes the corpus build
runs after chunking -- exactly what the served ``*.chunks.jsonl`` files and the
corpus report rows are about. ``bangla_gpt_api.nctb.chunking`` re-exports every
name here, so the pipeline, the scripts and the tests keep their import path.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


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
