"""Evidence-budget contract for grounded generation (RAG audit F-06/B3).

Pins the guarantee that NO grounded generation path can pour an unbounded
textbook mass into one provider call: hits are trimmed greedily from the
top-ranked list, the first hit is always kept (an empty evidence list would
turn the generators into ``ProviderError``), and what is trimmed never
returns a partial citation.
"""

from __future__ import annotations

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.services.generators.evidence import (
    DEFAULT_MAX_EVIDENCE_CHARS,
    trim_evidence_hits,
    trim_evidence_texts,
)


def _meta() -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="s",
        chapter="আলো",
    )


def _hit(cid: str, words: int, score: float) -> Hit:
    text = " ".join(f"শব্দ{i}" for i in range(words))
    return Hit(chunk=Chunk(id=cid, text=text, meta=_meta()), score=score)


def test_greedy_trim_keeps_top_hits_under_budget() -> None:
    hits = [_hit("a", 200, 5.0), _hit("b", 200, 4.0), _hit("c", 200, 3.0)]
    # a 200-word Bangla unit measures ~1489 chars: two fit 3200, three do not.
    kept = trim_evidence_hits(hits, max_chars=3200)
    assert [h.chunk.id for h in kept] == ["a", "b"]


def test_first_hit_is_never_dropped_even_when_over_budget() -> None:
    huge = [_hit("a", 5000, 5.0), _hit("b", 10, 4.0)]
    kept = trim_evidence_hits(huge, max_chars=1000)
    assert [h.chunk.id for h in kept] == ["a"]


def test_texts_trim_matches_hit_semantics() -> None:
    texts = ["x" * 4000, "y" * 4000, "z" * 4000]
    assert trim_evidence_texts(texts, max_chars=9000) == texts[:2]
    assert trim_evidence_texts([], max_chars=9000) == []


def test_default_budget_is_generous_but_real() -> None:
    # Non-binding for the bundled sample corpus (3 chunks × ≤ ~2.5k chars),
    # a hard ceiling for the top_k=6 teacher generators.
    assert 4000 <= DEFAULT_MAX_EVIDENCE_CHARS <= 20000
