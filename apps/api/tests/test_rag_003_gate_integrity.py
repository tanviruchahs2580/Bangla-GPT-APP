"""RAG-003: the grounding gate must not be able to certify a different question.

This file locks the two ways a *successful* gate verdict was reachable without
the corpus containing the question, both measured on the shipped code and both
verified by execution before the fix:

**1. A spelling repair carried the verdict.** ``match_spelling`` admits a
candidate at edit similarity >= 0.6. At that boundary a misspelling and a
different word are indistinguishable, so ``বিরিয়ানি`` (df 0) repaired to
``বিষয়াদি`` and answered with three citations from a mathematics textbook at
coverage 1.0 and confidence 0.9086. Measured similarities from the real
vocabulary show why no threshold fixes it:

    ===========================  ======  ==================================
    pair                         sim     what it is
    ===========================  ======  ==================================
    স্বরন্ধি -> স্বরসন্ধি             0.889   a misspelling
    কোশ -> কোষ                     0.667   a misspelling (documented case)
    বিরিয়ানি -> বিষয়াদি            0.667   a different word
    টাকা -> টীকা                   0.750   a different word
    ট্রেন -> ট্রেড                   0.800   a different word
    পাইথাগোরাস -> পিথাগোরাসের        0.636   a misspelling
    ===========================  ======  ==================================

``কোশ``/``কোষ`` and ``বিরিয়ানি``/``বিষয়াদি`` score *identically*; the
fabricating ``ট্রেন``/``ট্রেড`` scores higher than the legitimate
``পাইথাগোরাস``/``পিথাগোরাসের``. The repair keeps its retrieval power and
loses its vote.

**2. A question with no content term passed on the stop-word fallback.** The
fallback existed to avoid "scoring an empty term set as instant
groundability" and caused exactly that: every stem of ``কি?`` is covered by any
textbook sentence, so ``কি?``, ``কেন?``, ``কোথায়?`` and the committed golden
*negative* ``এটা কী?`` all passed (``ask("কি?")`` -> grounded, 3 sources,
confidence 0.9265).
"""

from __future__ import annotations

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.services.tutor import TutorService


def _meta(chapter: str = "অনুশীলনী") -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="mathematics",
        book="গণিত",
        source="fixture",
        chapter=chapter,
        page=1,
    )


class _Hit:
    """Minimal Hit stand-in: the gate only reads ``chunk`` and ``score``."""

    def __init__(self, chunk: Chunk, score: float) -> None:
        self.chunk = chunk
        self.score = score


class _RepairOnlyStats:
    """A vocabulary where the asked word exists *only* as someone else's typo.

    ``বিষয়াদি`` is in the corpus; ``বিরিয়ানি`` is not, but the spelling lane
    offers ``বিষয়াদি`` as a repair — which is the shipped situation.
    """

    total_documents = 100

    def document_frequency(self, term: str) -> int:
        return {"বিষয়াদি": 4}.get(term, 0)

    def match_spelling(self, term: str) -> list[str]:
        return ["বিষয়াদি"] if term == "বিরিয়ানি" else []


def _fabricating_setup() -> tuple[TutorService, list[_Hit]]:
    chunk = Chunk(
        id="c1",
        meta=_meta(),
        text="বিষয়াদি নির্ধারণ করে শিক্ষাক্রম প্রণয়ন করা হয়।",
    )
    tutor = TutorService(
        index=BM25Index([]), provider=MockLLMProvider(), term_stats=_RepairOnlyStats()
    )
    return tutor, [_Hit(chunk, 9.0)]


def test_repair_only_term_cannot_certify_an_answer() -> None:
    """The measured fabrication: coverage used to read 1.0 and the turn passed."""
    tutor, hits = _fabricating_setup()
    # The repair really is available — this is not a "no candidate" case.
    assert "বিষয়াদি" in hits[0].chunk.text
    coverage, passed = tutor._coverage_details("বিরিয়ানি", hits)
    assert passed is False, "a repair-resolved term must not carry the verdict alone"
    assert coverage == 0.0, (
        "a refused turn must report the coverage the verdict used, not the repair-widened number"
    )


def test_repair_only_term_reports_zero_even_when_it_appears_in_the_evidence() -> None:
    """The repaired surface being present is not the question being answerable."""
    tutor, hits = _fabricating_setup()
    for question in ("বিরিয়ানি", "বিরিয়ানি কী?", "বিরিয়ানির দাম কত?"):
        coverage, passed = tutor._coverage_details(question, hits)
        assert passed is False, question
        assert coverage == 0.0, question


def test_in_corpus_term_still_passes() -> None:
    """The control: the same shape, but the asked word IS in the corpus."""
    tutor, hits = _fabricating_setup()
    coverage, passed = tutor._coverage_details("বিষয়াদি কী?", hits)
    assert passed is True
    assert coverage == 1.0


def test_mixed_question_is_decided_on_the_in_corpus_terms() -> None:
    """A repair may accompany a real term; it just cannot be the whole case."""
    tutor, hits = _fabricating_setup()
    coverage, passed = tutor._coverage_details("বিষয়াদি ও বিরিয়ানি", hits)
    # বিষয়াদি is genuinely covered and is what the verdict rests on.
    assert passed is True
    assert coverage == 1.0


def test_question_without_content_terms_refuses() -> None:
    """The stop-word fallback is gone: nothing to stand on means refusal.

    ``কত?, ``কি?'', ``কোথায়?`` and the golden negative ``এটা কী?`` were all
    answered with citations before this.
    """
    tutor, hits = _fabricating_setup()
    for question in ("কি?", "কেন?", "কোথায়?", "কিভাবে?", "কত?", "এটা কী?"):
        coverage, passed = tutor._coverage_details(question, hits)
        assert passed is False, question
        assert coverage == 0.0, question


def test_question_without_content_terms_refuses_even_with_strong_hits() -> None:
    """A high-scoring hit must not rescue an unverifiable question."""
    chunk = Chunk(
        id="c9",
        meta=_meta(),
        text="শিক্ষাক্রম প্রণয়নের নীতিমালা এখানে বর্ণিত হয়েছে।",
    )
    tutor = TutorService(
        index=BM25Index([]), provider=MockLLMProvider(), term_stats=_RepairOnlyStats()
    )
    coverage, passed = tutor._coverage_details("এটা কী?", [_Hit(chunk, 99.0)])
    assert (coverage, passed) == (0.0, False)
