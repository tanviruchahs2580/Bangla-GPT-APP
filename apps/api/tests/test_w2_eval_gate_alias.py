"""Grounding gate: roman/glossary candidates are alternatives (F-051 measure).

The Banglish stratum of golden v3 measured 0/74 grounded although retrieval
returned the correct chapter for every item: `_coverage_details` appended every
roman candidate of an ASCII token as a separate must-cover term, so "bhasha o
brn ki?" had to cover বাষ্প, ভাঙা, ত্বরণ, বর্গ ... as well and scored 0.1966
against the right chunk. A raw term is now one group of alternative surfaces:
absent only when no candidate is in the corpus, covered when any candidate
matches. These tests pin both halves of that rule.
"""

from __future__ import annotations

import asyncio

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.services.tutor import TutorService

# বাংলা ও বর্ণ -- class 6 bangla; romanised by the repo's own transliterator.
_CHAPTER = "ভাষা ও বর্ণ"
_ROMAN_QUESTION = "bhasha o brn ki?"


def _tutor() -> TutorService:
    index = HybridIndex(load_sample_corpus(), build_embedder(Settings(env="test")))
    return TutorService(
        index=index,
        provider=MockLLMProvider(),
        term_stats=index.term_stats,
    )


def test_roman_question_grounds_on_its_own_chapter() -> None:
    tutor = _tutor()
    response = asyncio.run(tutor.ask(_ROMAN_QUESTION, 6, "bangla"))
    assert response.grounded is True
    assert response.sources
    assert response.sources[0].chapter == _CHAPTER


def test_roman_alternatives_do_not_multiply_must_cover_terms() -> None:
    tutor = _tutor()
    hits = tutor.index.search(_ROMAN_QUESTION, class_level=6, subject="bangla", top_k=3)
    coverage, passed = tutor._coverage_details(_ROMAN_QUESTION, hits)
    assert passed is True
    assert coverage == 1.0


def test_romanic_out_of_corpus_question_still_refuses() -> None:
    """Alternatives widen one term, they do not weaken the absence budget."""
    tutor = _tutor()
    response = asyncio.run(tutor.ask("tokio te temperature koto?", 6, "science"))
    assert response.grounded is False
    assert response.refused_reason == "insufficient_evidence"
