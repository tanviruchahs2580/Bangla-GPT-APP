"""F-002 / RAG-15: the grounding gate must apply the documented out-of-corpus budget.

The gate used to keep only content terms with df > 0 and measure coverage over
the survivors, so an out-of-corpus question sharing ONE ubiquitous token with
the corpus scored coverage 1.0 and was answered with citations from unrelated
sections (E-RAG-15 probe: 'ক্রিকেট বিশ্বকাপ ফাইনালে কে জিতেছিল?' grounded with
coverage 1.0 on কে, df=183). docs/RAG_ARCHITECTURE.md documents the rule the
code must implement: ">= 2 content terms absent from the corpus -> refuse".

The hermetic fixture reproduces the exact failure shape (one ubiquitous
in-corpus term, all subject terms absent) and pins both sides of the budget:
raising the budget to the pre-fix value re-creates the false answer, and the
documented budget refuses it. The real-corpus test pins the four family-C
probe questions from E-RAG-15 and skips when the untracked corpus is absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.services.tutor import TutorService

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CORPUS = REPO_ROOT.parent / "data" / "nctb"
REAL_CORPUS_AVAILABLE = (REAL_CORPUS / "quality_report.json").exists() and any(
    (REAL_CORPUS / "normalized").glob("*.chunks.jsonl")
)

#: The four family-C questions of scripts/evaluate_nctb_retrieval.py (the same
#: probes E-RAG-15 ran). None of them is answerable from an NCTB textbook.
FAMILY_C = [
    "ক্রিকেট বিশ্বকাপ ফাইনালে কে জিতেছিল?",
    "ঢাকার সেরা বিরিয়ানির দোকান কোথায়?",
    "ইউক্লিডের পঞ্চম স্বতঃসিদ্ধ ব্যাখ্যা কর",
    "গত সপ্তাহের ডলারের দাম কত?",
]


def _meta() -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2012,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="fixture",
        chapter="বল ও গতি",
        page=1,
    )


def _tutor() -> TutorService:
    # Every chunk carries the ubiquitous interrogative কে (the token the probe
    # measured at df=183 on the real corpus) plus curriculum vocabulary.
    chunks = [
        Chunk(
            id=f"c{i}",
            meta=_meta(),
            text=f"বল ও গতির সূত্র কে দিয়েছেন এবং কেন পঞ্চম উদাহরণটি প্রয়োজন। সংখ্যা {i}",
        )
        for i in range(1, 5)
    ]
    index = BM25Index(chunks)
    return TutorService(index=index, provider=MockLLMProvider(), term_stats=index.term_stats)


def test_out_of_corpus_question_with_one_ubiquitous_term_is_refused() -> None:
    tutor = _tutor()
    question = FAMILY_C[0]  # ক্রিকেট বিশ্বকাপ ফাইনালে কে জিতেছিল?
    hits = tutor.index.search(question, class_level=6, top_k=3)
    _coverage, passed = tutor._coverage_details(question, hits)
    assert passed is False, "the documented >=2-absent-content-terms budget must refuse"


def test_pre_fix_budget_would_have_answered_it() -> None:
    """The failing side of the regression: the old rule passes this question."""
    tutor = _tutor()
    question = FAMILY_C[0]
    hits = tutor.index.search(question, class_level=6, top_k=3)
    original = TutorService.OUT_OF_CORPUS_ABSENT_BUDGET
    TutorService.OUT_OF_CORPUS_ABSENT_BUDGET = 10**6
    try:
        coverage, passed = tutor._coverage_details(question, hits)
    finally:
        TutorService.OUT_OF_CORPUS_ABSENT_BUDGET = original
    # One in-corpus survivor (কে) yielded coverage 1.0 -- the measured defect.
    assert passed is True and coverage == 1.0


@pytest.mark.parametrize("question", FAMILY_C)
def test_every_family_c_question_is_refused(question: str) -> None:
    tutor = _tutor()
    hits = tutor.index.search(question, class_level=6, top_k=3)
    _coverage, passed = tutor._coverage_details(question, hits)
    assert passed is False, question


def test_in_corpus_question_still_grounds_under_the_budget() -> None:
    tutor = _tutor()
    question = "বল ও গতির সূত্র কে দিয়েছেন?"
    hits = tutor.index.search(question, class_level=6, top_k=3)
    _coverage, passed = tutor._coverage_details(question, hits)
    assert passed is True


def test_single_absent_content_term_still_answers() -> None:
    """One absent term is inside the budget (the documented allowance)."""
    tutor = _tutor()
    # বল, গতি, সূত্র are all in the fixture corpus; অজানা is the only absence.
    question = "বল ও গতির সূত্র অজানা কেন?"
    hits = tutor.index.search(question, class_level=6, top_k=3)
    _coverage, passed = tutor._coverage_details(question, hits)
    assert passed is True


@pytest.mark.skipif(not REAL_CORPUS_AVAILABLE, reason="real NCTB corpus not present")
def test_family_c_questions_refuse_on_the_real_corpus_build() -> None:
    from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    chunks = load_nctb_corpus(
        REAL_CORPUS / "normalized",
        quality_report_path=REAL_CORPUS / "quality_report.json",
        multi_class_fallback=True,
    )
    assert chunks, "expected an indexable corpus build"
    served = HybridIndex(chunks, HashingEmbedder())
    tutor = TutorService(index=served, provider=MockLLMProvider(), term_stats=served.term_stats)
    for question in FAMILY_C:
        hits = tutor._retrieve(question, class_level=6, subject=None)
        _coverage, passed = tutor._coverage_details(question, hits)
        assert passed is False, question
