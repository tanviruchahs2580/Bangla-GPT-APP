"""RAG-002 regression: a repaired Bangla typo must reach the grounding gate.

Retrieval already repairs one-character Bangla misspellings --
``BM25Index._query_side_expansions`` routes an unknown Bangla token through
``CorpusVocabulary.match_spelling`` -- so a misspelled query retrieves the same
top chunk as the correctly spelled one. The coverage gate, however, ran its
absence/term-weighting on an **exact** ``document_frequency`` lookup, so the
typo counted as an absent content term and the turn refused while the right
evidence was already retrieved.

Measured on the served corpus: ``"স্বরন্ধি কী?"`` returned the identical top
chunk (score 12.295 vs 7.395 for the correct spelling) and refused at
coverage 0.0; ``"স্বরসন্ধি কী?"`` grounded at coverage 1.0. Golden-v3 stratum
``bn_typo`` sat at 6/37.

The fix resolves query tokens through the same spelling lane before the
absence/coverage computation, exactly as ``_resolve_query_groups`` already
does for ASCII/romanised tokens. No threshold moved. The negative controls
pin that a genuinely absent term -- repairable or not -- still refuses, so
``OUT_OF_CORPUS_ABSENT_BUDGET`` keeps its meaning.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.providers.mock import MockLLMProvider
from bangla_gpt_api.retrieval.bm25 import BM25Index
from bangla_gpt_api.services.tutor import TutorService


def _meta(chapter: str = "সন্ধি") -> CurriculumMeta:
    return CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="bangla",
        book="বাংলা",
        source="fixture",
        chapter=chapter,
        page=1,
    )


def _tutor() -> tuple[TutorService, BM25Index]:
    chunks = [
        Chunk(
            id="c1",
            meta=_meta(),
            text="স্বরসন্ধি হলো পাশাপাশি দুটি স্বরের মিলন, যেখানে স্বর দুটি একসঙ্গে উচ্চারিত হয়।",
        ),
        Chunk(
            id="c2",
            meta=_meta(),
            text="ব্যঞ্জনসন্ধি হলো ব্যঞ্জনবর্ণের সঙ্গে স্বর বা ব্যঞ্জনের মিলন।",
        ),
    ]
    index = BM25Index(chunks)
    return (
        TutorService(index=index, provider=MockLLMProvider(), term_stats=index.term_stats),
        index,
    )


@pytest.mark.parametrize("typo", ["স্বরন্ধি", "স্বরসন্ধী"])
def test_misspelled_question_passes_when_the_spelling_lane_repairs_it(typo: str) -> None:
    tutor, index = _tutor()
    # The repair belongs to the retrieval lane that already runs in production.
    assert "স্বরসন্ধি" in index.vocabulary.match_spelling(typo)
    question = f"{typo} কী?"
    hits = tutor._retrieve(question, class_level=6, subject=None)
    assert hits, "the spelling lane must still retrieve a one-character typo"
    assert hits[0].chunk.id == "c1"
    coverage, passed = tutor._coverage_details(question, hits)
    assert passed is True, (
        f"repaired term must count as in-corpus, got coverage={coverage} for {question!r}"
    )
    assert coverage == 1.0


def test_typo_verdict_has_parity_with_the_correct_spelling() -> None:
    tutor, _index = _tutor()
    typo_hits = tutor._retrieve("স্বরন্ধি কী?", class_level=6, subject=None)
    spelled_hits = tutor._retrieve("স্বরসন্ধি কী?", class_level=6, subject=None)
    assert typo_hits and spelled_hits
    assert typo_hits[0].chunk.id == spelled_hits[0].chunk.id
    assert tutor._coverage_details("স্বরন্ধি কী?", typo_hits) == tutor._coverage_details(
        "স্বরসন্ধি কী?", spelled_hits
    )


def test_genuinely_absent_term_with_no_repair_still_refuses() -> None:
    tutor, index = _tutor()
    # No vocabulary term starts with ঝ, so the spelling lane cannot invent a
    # repair for a genuinely out-of-corpus word.
    assert index.vocabulary.match_spelling("ঝটিকা") == []
    hits = tutor._retrieve("ঝটিকা কী?", class_level=6, subject=None)
    coverage, passed = tutor._coverage_details("ঝটিকা কী?", hits)
    assert passed is False
    assert coverage == 0.0


def test_two_absent_terms_still_hit_the_out_of_corpus_budget() -> None:
    tutor, index = _tutor()
    absent = "ঝটিকা ট্রাম্পেট কী?"
    for term in ("ঝটিকা", "ট্রাম্পেট"):
        assert index.vocabulary.match_spelling(term) == []
    hits = tutor._retrieve(absent, class_level=6, subject=None)
    coverage, passed = tutor._coverage_details(absent, hits)
    # Refused by the absence budget, not by a low-score accident.
    assert passed is False
    assert coverage == 0.0


def test_repair_carried_only_by_a_lower_ranked_hit_is_not_admitted() -> None:
    """Shipped-corpus shape: "'ভাষা ও বর্ণ' অধ্যায়ে কী কী পার্থক্য আছে?"

    The spelling lane repairs অধ্যায়ে -> অনুযায়ী, and only a lower-ranked
    chunk carries অনুযায়ী. With union-scoped admission that repair weighed
    down every hit's coverage (0.679 -> 0.477) and refused an answerable
    question; the shipped rule admits a repair only from the top-ranked
    evidence, so the answering hit still passes.
    """

    class _Stats:
        total_documents = 10

        def document_frequency(self, term: str) -> int:
            return {"ভগ্নাংশ": 2, "অনুযায়ী": 1}.get(term, 0)

        def match_spelling(self, term: str) -> list[str]:
            return ["অনুযায়ী"] if term == "অধ্যায়ে" else []

    class _Hit:
        def __init__(self, chunk: Chunk, score: float) -> None:
            self.chunk = chunk
            self.score = score

    best = Chunk(id="c1", meta=_meta(), text="ভগ্নাংশ হলো গোটা জিনিসের একটি অংশ।")
    lower = Chunk(id="c2", meta=_meta(), text="নিয়ম অনুযায়ী কাজ করতে হয়।")
    tutor = TutorService(index=BM25Index([]), provider=MockLLMProvider(), term_stats=_Stats())
    coverage, passed = tutor._coverage_details(
        "ভগ্নাংশ অধ্যায়ে কী?", [_Hit(best, 9.0), _Hit(lower, 1.0)]
    )
    assert passed is True, coverage
    assert coverage == 1.0


def test_repair_carried_by_the_top_hit_still_does_not_dilute_the_answering_hit() -> None:
    """Shipped-corpus shape: "'সন্ধি' অধ্যায়ে কী কী পার্থক্য আছে?"

    Here the top-ranked chunk *does* carry the spurious repair
    (অধ্যায়ে -> অনুযায়ী, df=1 so maximum weight) while the answerable hit
    covers only সন্ধি; with the repair weighted everywhere the hit that
    actually answers dropped to 0.305 and refused. A repair resolved term is
    an optional surface: it must not enter a hit's denominator unless the hit
    carries the repaired word.
    """

    class _Stats:
        total_documents = 10

        def document_frequency(self, term: str) -> int:
            return {"সন্ধি": 2, "অনুযায়ী": 1, "পার্থক্য": 3}.get(term, 0)

        def match_spelling(self, term: str) -> list[str]:
            return ["অনুযায়ী"] if term == "অধ্যায়ে" else []

    class _Hit:
        def __init__(self, chunk: Chunk, score: float) -> None:
            self.chunk = chunk
            self.score = score

    # The chapter label is indexed too (indexable_text), so the top chunk's
    # chapter must not be সন্ধি; otherwise it would carry the term by itself.
    top = Chunk(id="c1", meta=_meta(chapter="প্রচ্ছদ"), text="নিয়ম অনুযায়ী কাজ করতে হয়।")
    answer = Chunk(id="c2", meta=_meta(), text="সন্ধি হলো দুটি বর্ণের মিলন।")
    tutor = TutorService(index=BM25Index([]), provider=MockLLMProvider(), term_stats=_Stats())
    coverage, passed = tutor._coverage_details(
        "সন্ধি অধ্যায়ে কী কী পার্থক্য আছে?",
        [_Hit(top, 6.9), _Hit(answer, 4.5)],
    )
    assert passed is True, coverage
    # The answering hit covers সন্ধি (df=2) against the uncovered but
    # in-corpus পার্থক্য (df=3): ln(6) / (ln(6) + ln(13/3)) == 0.5499. With the
    # repair wrongly in the denominator it was 0.317 and refused.
    assert coverage == 0.5499


def test_repair_candidates_that_are_not_vocabulary_cannot_manufacture_coverage() -> None:
    """A repaired surface counts only if it genuinely exists in the corpus."""

    class _FakeStats:
        total_documents = 10

        def document_frequency(self, term: str) -> int:
            return 0  # nothing is in this fake corpus, including the "repair"

        def match_spelling(self, term: str) -> list[str]:
            return ["নকলশব্দ"]  # a fabricated candidate, df == 0

    class _Hit:
        def __init__(self) -> None:
            self.chunk = Chunk(
                id="c9", meta=_meta(), text="নকলশব্দ হলো একটি বানানো শব্দ যার কোনো অস্তিত্ব নেই।"
            )
            self.score = 5.0

    tutor = TutorService(index=BM25Index([]), provider=MockLLMProvider(), term_stats=_FakeStats())
    coverage, passed = tutor._coverage_details("স্বরন্ধি কী?", [_Hit()])
    assert passed is False
    assert coverage == 0.0
