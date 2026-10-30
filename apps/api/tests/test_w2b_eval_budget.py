"""Budgeted evidence assembly at the tutor call site (F-129/RAG-10).

The mechanism (retrieval.context.assemble_evidence) and its tests existed, but
no production path called it: the generator still received every hit ``top_k``
returned. These tests pin the call site on both answer paths -- the prompt, the
citations and the trace must describe one and the same evidence set -- and the
budget's determinism for a direct build_evidence_prompt caller.
"""

from __future__ import annotations

import asyncio

from bangla_gpt_api.config import Settings
from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.bm25 import Hit
from bangla_gpt_api.retrieval.context import EVIDENCE_TOKEN_BUDGET, evidence_tokens
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import TutorService, build_evidence_prompt

_QUESTION = "কোষ কী?"
_SENTENCE = "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক। "


def _hit(chunk_id: str, text: str, score: float) -> Hit:
    return Hit(
        chunk=Chunk(
            id=chunk_id,
            text=text,
            meta=CurriculumMeta(
                curriculum_year=2012,
                class_level=6,
                subject="science",
                book="বিজ্ঞান",
                source="stub",
                chapter="অধ্যায় ১",
            ),
        ),
        score=score,
    )


def _fat_hit(chunk_id: str, score: float) -> Hit:
    text = _SENTENCE * 200
    hit = _hit(chunk_id, text, score)
    assert evidence_tokens(hit) > EVIDENCE_TOKEN_BUDGET
    return hit


class _FatIndex:
    """Duck-typed RankingIndex serving three over-budget hits."""

    def __init__(self, hits: list[Hit]) -> None:
        self._hits = hits
        self.searches = 0

    def search(self, question, *, class_level=None, subject=None, chapter=None, top_k=3):
        self.searches += 1
        return self._hits[:top_k]


class _RecordingProvider(MockLLMProvider):
    name = "stub-budget"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt, *, system=None, image=None):  # type: ignore[override]
        self.prompts.append(prompt)
        return _SENTENCE.strip()

    async def stream(self, prompt, *, system=None, image=None):  # type: ignore[override]
        self.prompts.append(prompt)
        yield _SENTENCE.strip()


def test_build_evidence_prompt_drops_the_over_budget_tail() -> None:
    hits = [_fat_hit("best", 3.0), _hit("small", _SENTENCE, 2.0), _hit("tail", _SENTENCE, 1.0)]
    prompt = build_evidence_prompt(hits, _QUESTION)
    # The best hit alone exceeds the budget and survives; the affordable tail
    # takes whatever budget is left.
    assert prompt.count("<evidence>") < len(hits)
    assert _SENTENCE.strip() in prompt


def test_tutor_prompt_citations_and_trace_share_one_evidence_set() -> None:
    provider = _RecordingProvider()
    hits = [_fat_hit("best", 3.0), _fat_hit("second", 2.0), _fat_hit("third", 1.0)]
    tutor = TutorService(index=_FatIndex(hits), provider=provider)
    response = asyncio.run(tutor.ask(_QUESTION, 6, "science"))
    assert response.grounded is True
    assert provider.prompts and provider.prompts[0].count("<evidence>") == 1
    assert [source.excerpt for source in response.sources] == [hits[0].chunk.text]
    traces = tutor.trace_store.recent(1)
    assert traces and traces[0].chunk_ids == ["best"]


def test_streaming_path_uses_the_same_selection() -> None:
    provider = _RecordingProvider()
    hits = [_fat_hit("best", 3.0), _fat_hit("second", 2.0)]
    tutor = TutorService(index=_FatIndex(hits), provider=provider)

    async def consume():
        final = None
        async for event in tutor.ask_stream(_QUESTION, 6, "science"):
            if event.type == "final":
                final = event.response
        return final

    response = asyncio.run(consume())
    assert response is not None and response.grounded is True
    assert provider.prompts and provider.prompts[0].count("<evidence>") == 1
    assert [source.excerpt for source in response.sources] == [hits[0].chunk.text]


def test_sample_corpus_stays_inside_the_budget() -> None:
    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    hits = index.search(_QUESTION, class_level=6, subject="science", top_k=3)
    assert sum(evidence_tokens(hit) for hit in hits) <= EVIDENCE_TOKEN_BUDGET
    prompt = build_evidence_prompt(hits, _QUESTION)
    # Nothing is dropped when the evidence fits: the budget changes no
    # committed-set behaviour.
    assert prompt.count("<evidence>") == len(hits)
