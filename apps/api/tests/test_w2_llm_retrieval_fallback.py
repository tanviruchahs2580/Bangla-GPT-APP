"""Retrieval fallback isolation (RAG-28).

The contract: when the hybrid retrieval pipeline (or its reranker) raises, the
turn degrades to the lexical lane if it can, and when nothing can serve it the
answers must refuse. Under no failure may an uncited answer be presented as
grounded.
"""

from __future__ import annotations

import asyncio

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import TutorService

_QUESTION = "কোষ কী?"


class _ExplodingIndex:
    """Index whose fused pipeline raises; the lexical lane still works."""

    def __init__(self, inner: HybridIndex) -> None:
        self.bm25 = inner.bm25
        self.term_stats = inner.term_stats

    def search(self, *args, **kwargs):
        raise RuntimeError("hybrid lane unavailable")


class _ExplodingLanes:
    """Index whose fused pipeline and lexical lane both raise."""

    def __init__(self, inner: HybridIndex) -> None:
        self.bm25 = _ExplodingIndex(inner)
        self.term_stats = inner.term_stats

    def search(self, *args, **kwargs):
        raise RuntimeError("hybrid lane unavailable")


def _index() -> HybridIndex:
    return HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))


def test_hybrid_failure_degrades_to_lexical_and_still_cites() -> None:
    inner = _index()
    tutor = TutorService(
        index=_ExplodingIndex(inner),  # type: ignore[arg-type]
        provider=MockLLMProvider(),
        term_stats=inner.term_stats,
    )
    response = asyncio.run(tutor.ask(_QUESTION, 6, "science"))
    assert response.grounded is True
    assert response.sources, "a degraded turn still has to carry its citations"


def test_total_retrieval_failure_refuses_and_carries_no_source() -> None:
    inner = _index()
    tutor = TutorService(
        index=_ExplodingLanes(inner),  # type: ignore[arg-type]
        provider=MockLLMProvider(),
        term_stats=inner.term_stats,
    )
    response = asyncio.run(tutor.ask(_QUESTION, 6, "science"))
    assert response.grounded is False
    assert response.refused_reason == "insufficient_evidence"
    assert response.sources == []


def test_refusal_path_never_reaches_the_provider() -> None:
    """A retrieval failure must not generate: generation without evidence is
    exactly the uncited-answer failure the contract forbids."""

    class _RecordingProvider(MockLLMProvider):
        calls = 0

        async def generate(self, prompt, *, system=None, image=None):  # type: ignore[override]
            type(self).calls += 1
            return await super().generate(prompt, system=system, image=image)

    inner = _index()
    tutor = TutorService(
        index=_ExplodingLanes(inner),  # type: ignore[arg-type]
        provider=_RecordingProvider(),
        term_stats=inner.term_stats,
    )
    response = asyncio.run(tutor.ask(_QUESTION, 6, "science"))
    assert response.grounded is False
    assert _RecordingProvider.calls == 0


def test_real_index_does_not_take_the_fallback() -> None:
    """The guarded path must be transparent on a healthy index."""
    inner = _index()
    tutor = TutorService(
        index=inner,
        provider=MockLLMProvider(),
        term_stats=inner.term_stats,
    )
    hits = tutor._retrieve_guarded(_QUESTION, 6, "science")
    assert hits
    assert hits[0].chunk.meta.chapter == "কোষ"
