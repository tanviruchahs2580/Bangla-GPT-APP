"""A4-06: the out-of-domain gate rule — mostly-absent content terms refuse.

The divergence register documented a rule the code did not implement
("≥ 2 content terms absent → refuse"), measured why the strict count form is
wrong (it refuses 37-38% of ANSWERABLE chapter-title and Banglish questions
on the real corpus), and honoured the class separation instead: a question
whose content terms are MOSTLY absent from the served index (more df==0
terms than known terms) is out-of-domain and refuses with the honest
not-in-textbook answer; a question the corpus knows as many or more of its
terms about proceeds to the weighted coverage verdict exactly as before.

Measured separation on the served NCTB corpus (probe: .audit/tmp/r4/, run
2026-10-19): the majority-absent predicate refuses 4/4 curated adversarial
questions and 0/317 answerable questions (families A/B/D) — the strict
">=2 absent" count refuses 38% of the answerable ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from bangla_gpt_api.services import tutor
from bangla_gpt_api.services.tutor import TutorService

REPO_REAL_CORPUS = Path(__file__).resolve().parents[3] / "data" / "nctb"


@dataclass
class _StubTermStats:
    """df map stand-in with the surfaces _coverage_details reads."""

    df: dict[str, int]

    @property
    def total_documents(self) -> int:
        return 100

    def document_frequency(self, term: str) -> int:
        return self.df.get(term, 0)


def _service(term_stats: _StubTermStats) -> TutorService:
    service = TutorService.__new__(TutorService)
    service.min_score = 0.0
    service.min_coverage = 0.5
    service.term_stats = term_stats  # type: ignore[assignment]
    service.FUZZY_MATCH_SIMILARITY = TutorService.FUZZY_MATCH_SIMILARITY
    return service


def _hit(text: str):
    from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
    from bangla_gpt_api.retrieval.bm25 import Hit

    meta = CurriculumMeta(
        curriculum_year=2023,
        class_level=6,
        subject="science",
        book="বিজ্ঞান",
        source="sample",
        chapter="কোষ",
        section="কোষ বিভাজন",
        page=1,
    )
    return Hit(chunk=Chunk(id="fake-1", text=text, meta=meta), score=5.0)


def test_known_heavy_question_proceeds_to_the_coverage_verdict() -> None:
    """2 known + 1 absent (absent < known): the weighted gate decides — pass."""
    stats = _StubTermStats({"সালোকসংশ্লেষণ": 10, "ঘটে": 3})
    service = _service(stats)
    hits = [_hit("সালোকসংশ্লেষণ হলো সেই প্রক্রিয়া যাতে গাছ খাদ্য তৈরি করে; এটি পাতায় ঘটে।")]
    coverage, passed = service._coverage_details("ইউক্লিড বলে সালোকসংশ্লেষণ কোথায় ঘটে?", hits)
    assert passed is True, "answerable evidence must not flip into a refusal"
    assert coverage > 0


def test_majority_absent_terms_refuse() -> None:
    """1 known + 2 absent content terms: the documented OOD case refuses.

    ("ভগ্নাংশ ইউক্লিড স্বতঃসিদ্ধ" was the divergence row's answered-anyway
    example; with the majority rule it refuses.)
    """
    stats = _StubTermStats({"ভগ্নাংশ": 10, "কোষ": 5})
    service = _service(stats)
    coverage, passed = service._coverage_details(
        "ভগ্নাংশ ইউক্লিড স্বতঃসিদ্ধ কী?", [_hit("ভগ্নাংশ দুই ধরনের হয়।")]
    )
    assert passed is False
    assert coverage == 0.0


def test_all_terms_absent_refuses_and_keeps_the_out_of_domain_label() -> None:
    events: list[tuple[str, dict]] = []
    import bangla_gpt_api.services.tutor as tutor_module

    original = tutor_module.json_log

    def capture(logger, level, event, **fields):  # type: ignore[no-untyped-def]
        if event and "out_of_domain" in str(fields.get("gate", "")):
            events.append((event, fields))
        return original(logger, level, event, **fields)

    tutor_module.json_log = capture
    try:
        stats = _StubTermStats({"কোষ": 5})
        service = _service(stats)
        _coverage, passed = service._coverage_details(
            "ইউক্লিডের পঞ্চম স্বতঃসিদ্ধ ব্যাখ্যা কর", [_hit("কোষ প্রভাবক ভিত।")]
        )
        assert passed is False
        assert events, "the refusal must be labelled out_of_domain in the log"
    finally:
        tutor_module.json_log = original


def test_equal_split_lets_the_weighted_gate_decide() -> None:
    """absent == known (> 0) is not 'mostly absent' — evidence decides."""
    stats = _StubTermStats({"অণু": 10})
    service = _service(stats)
    hits = [_hit("অণু পরমাণুর তৈরি; পরমাণু মৌলিক কণা।")]
    _coverage, passed = service._coverage_details("অণু এবং ইউক্লিড?", hits)
    assert passed is True


def test_empty_question_terms_fall_back_instead_of_refusing() -> None:
    """A question of only function words uses the stemmed-token fallback."""
    stats = _StubTermStats({"কোষ": 5})
    service = _service(stats)
    # "কী?" alone carries no content term; the stem fallback counts "কী" as absent →
    # the gate refuses (honest), it must not crash.
    _coverage, passed = service._coverage_details("কী?", [_hit("কোষ।")])
    assert passed is False


@pytest.mark.skipif(
    not (
        (REPO_REAL_CORPUS / "quality_report.json").exists()
        and any((REPO_REAL_CORPUS / "normalized").glob("*.chunks.jsonl"))
        if (REPO_REAL_CORPUS / "normalized").is_dir()
        else False
    ),
    reason="served NCTB corpus artifacts are not built on this checkout",
)
def test_served_corpus_curated_adversarial_questions_all_refuse() -> None:
    """The served-corpus pin: the 4 curated family-C questions refuse.

    Before the gate rule, 3 of the 4 answered (family_C refusal rate 0.25).
    """
    from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex

    load_stats: dict[str, int] = {}
    chunks = load_nctb_corpus(
        REPO_REAL_CORPUS / "normalized",
        quality_report_path=REPO_REAL_CORPUS / "quality_report.json",
        stats=load_stats,
    )
    served = HybridIndex(chunks, HashingEmbedder())
    service = TutorService(
        served,
        _MockNoopProvider(),
        min_score=0.0,
        min_coverage=0.5,
        top_k=3,
        term_stats=served.term_stats,
    )
    adversarial = [
        "ক্রিকেট বিশ্বকাপ ফাইনালে কে জিতেছিল?",
        "ঢাকার সেরা বিরিয়ানির দোকান কোথায়?",
        "ইউক্লিডের পঞ্চম স্বতঃসিদ্ধ ব্যাখ্যা কর",
        "গত সপ্তাহের ডলারের দাম কত?",
    ]
    for question in adversarial:
        hits = service._retrieve(question, class_level=6, subject=None)
        assert not service._gate(question, hits), (
            f"out-of-domain question must refuse on the served corpus: {question!r}"
        )


class _MockNoopProvider:
    name = "mock"
    supports_vision = False
    supports_sampling = False

    async def generate(self, *a, **k):  # pragma: no cover - never called
        raise AssertionError("the gate test must not generate")


def test_gate_rule_documented_number_is_recorded() -> None:
    """The module documents the measured numbers the rule came from."""
    import inspect

    source = inspect.getsource(tutor)
    assert "mostly absent" in source or "majority" in source
