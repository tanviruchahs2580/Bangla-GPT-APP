"""Parent/neighbor expansion (retrieval engine v2, stage 4).

The target flow expands the selected top evidence with its parent/neighbor
context BEFORE the grounding gate. The chunker's chapter-level parent id is
not a served object, so the served shape is NEIGHBOR expansion: adjacent
chunks within the same (source, class, chapter, section), ordered by page.

Contracts under test:

* one predecessor and one successor per selected hit, inserted immediately
  AFTER the hit they belong to;
* section-scoped: a hit never pulls a neighbor from another section;
* class-scoped: a class-6 hit never pulls a class-7 copy;
* rank order of the original hits is preserved and originals never move;
* an original is never duplicated by also being someone's neighbor;
* the expander is a pure function over (hits, corpus) so the tutor can hold
  it as an optional hook — default None keeps behavior byte-identical.
"""

from __future__ import annotations

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.retrieval.expansion import build_neighbor_expander


def _chunk(
    cid: str,
    text: str,
    *,
    section: str,
    page: int,
    class_level: int = 6,
    source: str = "book-a",
    chapter: str = "কোষ",
) -> Chunk:
    return Chunk(
        id=cid,
        text=text,
        meta=CurriculumMeta(
            curriculum_year=2026,
            class_level=class_level,
            subject="science",
            book="NCTB Science 6",
            source=source,
            chapter=chapter,
            section=section,
            page=page,
        ),
    )


def _hit(chunk: Chunk) -> Hit:
    return Hit(chunk=chunk, score=1.0)


def _corpus() -> list[Chunk]:
    return [
        _chunk("s1-p1", "প্রথম অংশ।", section="গঠন", page=10),
        _chunk("s1-p2", "দ্বিতীয় অংশ।", section="গঠন", page=11),
        _chunk("s1-p3", "তৃতীয় অংশ।", section="গঠন", page=12),
        _chunk("s2-p1", "অন্য শাখা।", section="বিভাজন", page=20),
        _chunk("s1-p1-c7", "উচ্চ শ্রেণির কপি।", section="গঠন", page=10, class_level=7),
    ]


def test_predecessor_and_successor_are_inserted_after_their_anchor() -> None:
    expand = build_neighbor_expander(_corpus())
    hits = [_hit(_chunk("s1-p2", "দ্বিতীয় অংশ।", section="গঠন", page=11))]
    expanded = expand(hits)
    ids = [h.chunk.id for h in expanded]
    assert ids == ["s1-p2", "s1-p1", "s1-p3"]


def test_section_scoping_never_crosses_sections() -> None:
    expand = build_neighbor_expander(_corpus())
    hits = [_hit(_chunk("s2-p1", "অন্য শাখা।", section="বিভাজন", page=20))]
    ids = [h.chunk.id for h in expand(hits)]
    assert ids == ["s2-p1"], "a lone section has no neighbors"


def test_class_scoping_is_absolute() -> None:
    expand = build_neighbor_expander(_corpus())
    hit = _hit(_chunk("s1-p1", "প্রথম অংশ।", section="গঠন", page=10))
    expanded = expand([hit])
    ids = [h.chunk.id for h in expanded]
    assert "s1-p1-c7" not in ids


def test_rank_order_is_preserved_and_no_duplicates() -> None:
    expand = build_neighbor_expander(_corpus())
    hits = [
        _hit(_chunk("s1-p1", "প্রথম অংশ।", section="গঠন", page=10)),
        _hit(_chunk("s1-p3", "তৃতীয় অংশ।", section="গঠন", page=12)),
    ]
    expanded = expand(hits)
    ids = [h.chunk.id for h in expanded]
    # originals stay in rank order; neighbors slot in after their anchors;
    # s1-p2 is s1-p1's successor AND would be s1-p3's predecessor — once only
    assert ids == ["s1-p1", "s1-p2", "s1-p3"]


def test_expansion_of_an_empty_selection_is_empty() -> None:
    expand = build_neighbor_expander(_corpus())
    assert expand([]) == []
