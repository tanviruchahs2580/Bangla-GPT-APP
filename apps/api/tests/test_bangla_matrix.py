"""BAN-001: Bangla robustness matrix (mock lane, sample corpus).

History: this matrix locked the honestly-measured behavior of the v1 lexical
gate — standard phrasing grounded, colloquial/mixed/Banglish/numeral/paraphrase
variants refused. Those refusals were the measured *weakness*, and the
docstring said the matrix would quantify the improvement when retrieval
advanced (update expectations with the eval-gate discipline, never silently).

That update is this change. The 2026-10-17 retrieval work (headings indexed in
the lexical lane, content-term coverage gate weighted by corpus document
frequency, spelling/Banglish/English-gloss query lanes) grounds the variants
that were refused for *surface-form* reasons; the eval-gate discipline was run
first and holds: the 634-item golden suite passes all six metrics (grounded
rate 1.0, faithfulness up 0.8547 → 0.8549) and the red-team set is still fully
refused with zero system-prompt leakage.

The numeral-framed variant now grounds as well: it names ভগ্নাংশ, the served
class-6 book section answers it, and the in-corpus-coverage rule stops the
"class framing" terms from diluting the verdict. The refusal that REMAINS is
the one that is correct: out-of-domain questions. It stays as a regression
guard, alongside :func:`test_matrix_never_hallucinates_bangla`.
"""

import pytest

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.services.tutor import TutorService


def _service() -> TutorService:
    return TutorService(
        index=BM25Index(load_sample_corpus()),
        provider=MockLLMProvider(),
        term_stats=BM25Index(load_sample_corpus()).term_stats,
    )


# (category, question, expect_grounded)
MATRIX: list[tuple[str, str, bool]] = [
    ("standard", "ভগ্নাংশ কী?", True),
    ("colloquial", "ভগ্নাংশটা কী জিনিস?", True),
    ("mixed", "ভগ্নাংশ কী? explain করো", True),
    ("banglish", "bhognangsho ki?", True),
    ("numeral", "৬ষ্ঠ শ্রেণির ভগ্নাংশ কী?", True),
    ("paraphrase", "ভগ্নাংশ কাকে বলে বুঝিয়ে বলো", True),
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
        else:
            # grounded answers must stand on the served corpus: every grounded
            # response carries its cited evidence, and the citation check has
            # passed (citation_verified is not None and True).
            assert response.citation_verified is True, (category, question)
