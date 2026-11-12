"""RAG v2 — parent/neighbor expansion of the selected top evidence.

The target flow expands the top relevant evidence with its surrounding
context BEFORE the grounding gate. In this corpus the chunker emits a
chapter-level parent id that is not a served object, so the served shape is
NEIGHBOR expansion: for each selected hit, the adjacent chunks within the
same ``(meta.source, meta.class_level, meta.chapter, meta.section)``,
ordered by ``(page, id)`` — one predecessor, one successor per side
(``per_side``). The chapter title itself already rides the indexed text
(``indexable_text`` folds headings in), so the parent signal is present
without a parent-chunk store; propagating the chunker's parent chain is an
ingestion/manifest change and is deliberately deferred.

Contracts (all pinned by tests/test_retrieval_expansion.py):

* neighbors slot in immediately AFTER the hit they belong to; the rank order
  of the original hits never changes;
* section- and class-scoped — absolute walls, mirroring the tenancy rules
  the lanes already enforce;
* an original is never duplicated by also being someone's neighbor;
* the returned list feeds ``context.assemble_evidence`` unchanged, so the
  768-token selection budget still bounds what the generator sees, and the
  grounding gate reads the assembled evidence exactly as before — no
  threshold moves.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.retrieval.bm25 import Hit


def build_neighbor_expander(
    chunks: list[Chunk],
    *,
    per_side: int = 1,
) -> Callable[[list[Hit]], list[Hit]]:
    """Build the expander over one immutable corpus (the index's chunk list)."""
    per_side = max(0, per_side)

    buckets: dict[tuple[str, int, str, str], list[tuple[int, str, Chunk]]] = defaultdict(list)
    for chunk in chunks:
        meta = chunk.meta
        buckets[(meta.source, meta.class_level, meta.chapter, meta.section or "")].append(
            (meta.page if meta.page is not None else 10**9, chunk.id, chunk)
        )
    for key in buckets:
        buckets[key].sort(key=lambda row: (row[0], row[1]))

    position: dict[str, tuple[str, int, str, str, int]] = {}
    for key, rows in buckets.items():
        for slot, (_page, _cid, chunk) in enumerate(rows):
            position[chunk.id] = (key[0], key[1], key[2], key[3], slot)

    def expand(hits: list[Hit]) -> list[Hit]:
        if not hits or per_side == 0:
            return list(hits)
        out: list[Hit] = []
        seen: set[str] = set()

        def _emit(hit: Hit) -> None:
            if hit.chunk.id not in seen:
                seen.add(hit.chunk.id)
                out.append(hit)

        for hit in hits:
            _emit(hit)
            info = position.get(hit.chunk.id)
            if info is None:
                continue
            source, class_level, chapter, section, slot = info
            rows = buckets[(source, class_level, chapter, section)]
            for offset in range(1, per_side + 1):
                for neighbor_slot in (slot - offset, slot + offset):
                    if 0 <= neighbor_slot < len(rows):
                        _emit(Hit(chunk=rows[neighbor_slot][2], score=hit.score))
        return out

    return expand
