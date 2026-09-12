"""BAN-001: Bangla robustness matrix (mock lane, sample corpus).

Locks in the CURRENT, honestly-measured behavior: exact standard phrasing
grounds; colloquial/mixed/Banglish/numeral/paraphrase variants refuse with
``insufficient_evidence`` instead of hallucinating. That refusal is the SAFE
default for a lexical-first retriever — when semantic embeddings (AI-001)
land, this matrix quantifies the improvement (update expectations then, with
the eval-gate discipline, never silently).
"""

import pytest

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.services.tutor import TutorService


def _service() -> TutorService:
    return TutorService(index=BM25Index(load_sample_corpus()), provider=MockLLMProvider())


# (category, question, expect_grounded)
MATRIX: list[tuple[str, str, bool]] = [
    ("standard", "ভগ্নাংশ কী?", True),
    ("colloquial", "ভগ্নাংশটা কী জিনিস?", False),
    ("mixed", "ভগ্নাংশ কী? explain করো", False),
    ("banglish", "bhognangsho ki?", False),
    ("numeral", "৬ষ্ঠ শ্রেণির ভগ্নাংশ কী?", False),
    ("paraphrase", "ভগ্নাংশ কাকে বলে বুঝিয়ে বলো", False),
    ("out-of-domain", "মঙ্গল গ্রহে প্রাণ আছে?", False),
]


@pytest.mark.parametrize("category,question,expected", MATRIX)
async def test_bangla_matrix(category: str, question: str, expected: bool) -> None:
    svc = _service()
    response = await svc.ask(question, class_level=6, subject="mathematics")
    assert response.grounded is expected, (category, question, response)
    if not expected:
        assert response.refused_reason == "insufficient_evidence"


async def test_matrix_never_hallucinates_bangla() -> None:
    """No variant may produce a grounded answer without evidence — the
    refusal copy itself must be well-formed Bangla."""
    svc = _service()
    for category, question, _expected in MATRIX:
        response = await svc.ask(question, class_level=6, subject="mathematics")
        if not response.grounded:
            assert "পাঠ্যবই" in response.answer, (category, response.answer)
