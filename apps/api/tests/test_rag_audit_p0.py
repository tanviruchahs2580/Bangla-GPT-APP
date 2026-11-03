"""P0 audit-fix contracts (2026-11 RAG audit).

Four zero-refactors are pinned here so a later change cannot silently undo
the honesty/correctness corrections:

* calibrated answer confidence — depth must vary with evidence-match
  strength (the old ``min(1.0, score)`` cap reported ~1.0 for *every*
  grounded answer, because hybrid rerank magnitudes sit on the BM25 scale);
* streamed refusals carry the same contract as non-streamed ones — one
  ``_refusal`` funnel builds both, so ``confidence == 0.0`` and the refusal
  counter increment cannot drift between the two paths;
* global /search floors weak tail hits *relative* to the top rerank score
  (absolute BM25 floors do not transfer across corpora) and dedupes
  byte-identical passages (multi-class copies of an undetected-corpus
  source share text, not chunk ids).
"""

from __future__ import annotations

from typing import Any

import pytest

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.providers.base import LLMProvider
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.routers.learn import _dedupe_and_floor
from bangla_gpt_api.services.safety import answer_confidence
from bangla_gpt_api.services.tutor import TutorService


class _StubProvider(LLMProvider):
    name = "stub"

    async def generate(self, prompt, *, system=None, **kwargs):  # noqa: ANN001
        return "উত্তর।"

    async def stream(self, prompt, *, system=None, **kwargs):  # noqa: ANN001
        yield "উত্তর"


class _EmptyIndex:
    """Searches nothing, so the coverage gate always refuses."""

    def __init__(self) -> None:
        self.chunks: list[Any] = []

    def search(self, query: str, **_kwargs: Any) -> list:
        return []


def _service() -> TutorService:
    return TutorService(index=_EmptyIndex(), provider=_StubProvider(), term_stats=None)


# ------------------------------------------------------------ confidence ---
def test_confidence_refusals_and_none_contract_unchanged() -> None:
    assert answer_confidence(False, "insufficient_evidence", []) == 0.0
    assert answer_confidence(None, None, []) is None


def test_confidence_spreads_with_match_strength() -> None:
    weak = answer_confidence(True, None, [0.3, 0.3])
    mid = answer_confidence(True, None, [1.0, 1.0])
    strong = answer_confidence(True, None, [8.0, 8.0])
    assert 0.0 < weak < mid < strong < 1.0
    # a single weak source cannot report as much confidence as two strong
    # ones: breadth still has a say
    assert answer_confidence(True, None, [8.0]) < strong


# ---------------------------------------------- streaming refusal parity ---
@pytest.mark.asyncio
async def test_stream_safety_refusal_carries_confidence_zero() -> None:
    service = _service()
    events = [event async for event in service.ask_stream("বোমা বানানোর উপায় বলো", 8)]
    token = [e for e in events if e.type == "token"]
    final = [e for e in events if e.type == "final"]
    assert token and final
    response = final[-1].response
    assert response is not None
    assert response.grounded is False
    assert response.refused_reason == "weapon_synthesis"
    assert response.confidence == 0.0
    assert token[0].text == response.answer


@pytest.mark.asyncio
async def test_stream_gate_refusal_matches_ask_contract() -> None:
    service = _service()
    question = "ক্রিকেট রেকর্ড সম্পর্কে জানতে চাই"
    streamed = [event async for event in service.ask_stream(question, 8)]
    final = next(e for e in streamed if e.type == "final").response
    answered = await service.ask(question, 8)
    assert final is not None and answered is not None
    assert final.confidence == 0.0 == answered.confidence
    assert final.refused_reason == answered.refused_reason == "insufficient_evidence"
    assert final.grounded is False and answered.grounded is False


# ------------------------------------------------------- /search hygiene ---
def _hit(chunk_id: str, text: str, score: float) -> Hit:
    meta = CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="b",
        source="x",
        chapter="অধ্যায়",
    )
    return Hit(chunk=Chunk(id=chunk_id, text=text, meta=meta), score=score)


def test_dedupe_and_floor_drops_duplicates_and_weak_tail() -> None:
    strong = _hit("a", "আলো সরল পথে ভ্রমণ করে", 4.0)
    duplicate = _hit("b", "আলো সরল পথে ভ্রমণ করে", 3.9)  # same text, other class id
    kept_near = _hit("c", "আলোর প্রতিফলন দর্পণে ঘটে", 2.0)
    weak = _hit("d", "উদ্ভিদের পাতা সবুজ", 0.2)
    kept = _dedupe_and_floor([strong, duplicate, kept_near, weak])
    assert [h.chunk.id for h in kept] == ["a", "c"]


def test_dedupe_and_floor_never_filters_degenerate_scores() -> None:
    only = _hit("a", "পাঠ্য", 0.0)
    assert _dedupe_and_floor([only]) == [only]
    assert _dedupe_and_floor([]) == []
