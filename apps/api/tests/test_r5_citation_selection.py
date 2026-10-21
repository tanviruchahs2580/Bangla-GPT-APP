"""A8-08: citation selection, the two citation readings, and the refusal split.

What is pinned here:

* ``services.safety.citation_coverage`` — per-passage coverage of an answer,
  the primitive the selection thresholds (and ``verify_citation`` wraps);
* ``services.tutor._cited_sources`` — an answer attaches the passages it
  leans on, in retrieval order, and falls back to the full retrieved set
  instead of dropping its evidence when the overlap is thin everywhere;
* the report's two citation readings (attached vs retrieved) and the
  refusal split by stratum, so the vocabulary-window golden items cannot pass
  as refused questions while their count stays visible;
* the online-loop join's subset rule: an answer citing part of a trace's
  retrieved set joins by citations only when exactly one trace fits.

Hermetic: no provider calls, no network.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.evaluation import generation as gen
from bangla_gpt_api.evaluation import online_loop
from bangla_gpt_api.schemas import SourceRef
from bangla_gpt_api.services.safety import citation_coverage
from bangla_gpt_api.services.tutor import CITATION_SELECTION_FLOOR, TutorService

PASSAGE_A = (
    "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক। প্রতিটি কোষ কোষঝিল্লি দিয়ে আবৃত থাকে "
    "এবং এর ভেতরে থাকে সাইটোপ্লাজম ও নিউক্লিয়াস। কোষ বিভাজনের মাধ্যমে নতুন কোষ "
    "সৃষ্টি হয় এবং প্রাণীর দেহ গঠিত হয়।"
)
PASSAGE_B = (
    "পরমাণু হলো মৌলের ক্ষুদ্রতম কণা। পরমাণুর কেন্দ্রে থাকে নিউক্লিয়াস এবং তা "
    "প্রোটন ও নিউট্রন দিয়ে গঠিত। ইলেকট্রন নিউক্লিয়াসের চারপাশে ঘোরে এবং রাসায়নিক "
    "বন্ধন তৈরি করে।"
)
#: Shares no content vocabulary with either passage above (a geometry rule),
#: which is what "off evidence" has to mean for a coverage floor to separate.
PASSAGE_C = (
    "ত্রিভুজের ক্ষেত্রফল = ½ × ভূমি × উচ্চতা। বৃত্তের পরিধি = 2πr এবং "
    "ক্ষেত্রফল = πr²। সমকোণী ত্রিভুজে অতিভুজের বর্গ অপর দুই বাহুর বর্গের "
    "সমষ্টির সমান।"
)


class _Chunk:
    def __init__(self, text: str) -> None:
        self.text = text
        self.meta = type(
            "Meta",
            (),
            {"book": "বিজ্ঞান", "chapter": "জীববিজ্ঞান", "section": "কোষ", "page": 1},
        )()


class _Hit:
    def __init__(self, text: str, score: float) -> None:
        self.chunk = _Chunk(text)
        self.score = score


def test_coverage_is_full_for_an_answer_with_no_scoreable_terms() -> None:
    # The convention verify_citation documents: nothing to contradict.
    assert citation_coverage("", PASSAGE_A) == 1.0
    assert citation_coverage("। ? ক", PASSAGE_A) == 1.0


def test_coverage_separates_the_passage_an_answer_leans_on() -> None:
    answer = "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক এবং এতে নিউক্লিয়াস থাকে।"
    on_evidence = citation_coverage(answer, PASSAGE_A)
    off_evidence = citation_coverage(answer, PASSAGE_C)
    assert on_evidence > 0.8, on_evidence
    assert off_evidence < CITATION_SELECTION_FLOOR, off_evidence


def test_cited_sources_keeps_only_the_passages_the_answer_leans_on() -> None:
    """The unrelated passage is dropped; a passage that merely shares generic
    Bangla terms (থাকে, হলো, এবং) can stay above the floor — measured, and the
    reason the report's attached-set precision lands near 0.87 on the live set
    rather than at 1.0."""
    answer = "কোষ হলো জীবদেহের গঠনগত ও কার্যগত একক এবং এতে নিউক্লিয়াস থাকে।"
    hits = [_Hit(PASSAGE_A, 3.0), _Hit(PASSAGE_B, 2.0), _Hit(PASSAGE_C, 1.0)]
    cited = [hit.chunk.text for hit in TutorService._cited_sources(answer, hits)]
    assert PASSAGE_A in cited
    assert PASSAGE_C not in cited, "the unrelated passage must be dropped"
    assert cited[0] == PASSAGE_A, "retrieval order is preserved"
    # the answer that leans on the second content passage keeps that one first
    other = "পরমাণুর কেন্দ্রে নিউক্লিয়াস থাকে এবং ইলেকট্রন চারপাশে ঘোরে।"
    leaned = [hit.chunk.text for hit in TutorService._cited_sources(other, hits)]
    assert PASSAGE_B in leaned and PASSAGE_C not in leaned


def test_cited_sources_falls_back_to_the_best_passage() -> None:
    """A thin overlap everywhere keeps ONE passage, not the whole set.

    The response must never lose its evidence because the overlap measurement
    came out low -- but attaching the full retrieved set in that case is where
    the imprecise citations came from (measured on the frozen split: section
    precision 0.8802 while neighbouring sections of the right chapter travelled
    with answers that did not lean on them). The best-covered passage is the
    one to keep, and it is kept even when every score is low.
    """
    answer = "এই উত্তরটি ভিন্ন জগতের শব্দে লেখা হয়েছে সম্পূর্ণ অন্যভাবে।"
    hits = [_Hit(PASSAGE_C, 3.0), _Hit(PASSAGE_B, 2.0)]
    kept = TutorService._cited_sources(answer, hits)
    assert len(kept) == 1, f"exactly the best passage is attached, got {len(kept)}"
    best = max(hits, key=lambda h: citation_coverage(answer, h.chunk.text))
    assert kept == [best]
    assert TutorService._cited_sources(answer, []) == []


def test_cited_sources_floor_is_the_declared_boundary() -> None:
    """A passage at the floor is kept; one just below it is dropped."""
    # Ten distinct content terms, so the coverage of one passage is simply the
    # share of them it carries: four terms = 0.40 (the floor), three = 0.30.
    answer = " ".join(f"অনন্য{i}" for i in range(10))
    at_floor = " ".join(f"অনন্য{i}" for i in range(4))
    below = " ".join(f"অনন্য{i}" for i in range(3))
    assert citation_coverage(answer, at_floor) == CITATION_SELECTION_FLOOR
    assert citation_coverage(answer, below) < CITATION_SELECTION_FLOOR
    kept = TutorService._cited_sources(answer, [_Hit(at_floor, 2.0), _Hit(below, 1.0)])
    assert [hit.chunk.text for hit in kept] == [at_floor]


def _source(chapter: str, section: str, page: int = 1) -> SourceRef:
    return SourceRef(book="বিজ্ঞান", chapter=chapter, section=section, page=page, score=1.0)


def test_report_carries_both_citation_readings() -> None:
    """Attached-set precision (the citations the reader sees) and
    retrieved-set precision (what retrieval returned) are both reported."""
    attached = [_source("কোষ", "কোষের প্রধান অংশ")]
    retrieved = [
        _source("কোষ", "কোষের প্রধান অংশ"),
        _source("কোষ", "কোষ কী"),
        _source("পানিচক্র", "পানিচক্র কী"),
    ]
    rows = [
        {
            "expect": "answer",
            "grounded": True,
            "sources": attached,
            "retrieved_sources": retrieved,
            "gold_chapter": "কোষ",
            "gold_section": "কোষের প্রধান অংশ",
            "answer": "উত্তর",
            "stratum": "definition",
        }
    ]
    metrics = gen.generation_metrics(rows)
    assert metrics["citation_precision"] == 1.0
    assert metrics["citation_precision_chapter"] == 1.0
    assert metrics["citation_precision_retrieved"] == pytest.approx(0.3333, abs=1e-4)
    assert metrics["citation_precision_chapter_retrieved"] == pytest.approx(0.6667, abs=1e-4)
    assert metrics["citations_total"] == 1
    assert metrics["citations_retrieved_total"] == 3


def test_refusals_are_split_by_stratum_and_probe_items_are_counted() -> None:
    """The headline rate keeps every answerable item; the stratum split and the
    vocabulary-window count travel next to it, so a refusal cluster on the
    term-window items is visible without dropping it from the headline."""
    rows = [
        {
            "expect": "answer",
            "grounded": False,
            "sources": [],
            "gold_chapter": "সেট",
            "gold_section": "উপসেট ও প্রকৃত উপসেট",
            "answer": "",
            "stratum": "contextual",
        },
        {
            "expect": "answer",
            "grounded": False,
            "sources": [],
            "gold_chapter": "কোষ",
            "gold_section": "কোষের প্রধান অংশ",
            "answer": "",
            "stratum": "definition",
        },
        {
            "expect": "answer",
            "grounded": True,
            "sources": [_source("কোষ", "কোষের প্রধান অংশ")],
            "gold_chapter": "কোষ",
            "gold_section": "কোষের প্রধান অংশ",
            "answer": "উত্তর",
            "stratum": "definition",
        },
    ]
    metrics = gen.generation_metrics(rows)
    assert metrics["false_refusal_rate"] == pytest.approx(0.6667, abs=1e-4)
    assert metrics["vocabulary_probe_items"] == 1
    assert "false_refusal_rate_questions" not in metrics
    assert metrics["false_refusal_by_stratum"]["contextual"]["refused"] == 1
    assert metrics["false_refusal_by_stratum"]["definition"]["rate"] == 0.5


def test_online_loop_joins_a_cited_subset_uniquely() -> None:
    """The answer now cites part of the trace's retrieved set; the join stays
    exact by requiring that exactly one unused trace fits."""
    meta = {
        "c1": ("কোষ", "কোষের প্রধান অংশ", 1),
        "c2": ("কোষ", "কোষ কী", 2),
        "c3": ("পানি", "পানিচক্র কী", 3),
        "c9": (" বল", "বল ও গতি", 9),
    }
    traces = [
        {"stage": "retrieval", "retrieved_ids": ["c1", "c2", "c3"], "evidence_chunks": 3},
        {"stage": "retrieval", "retrieved_ids": ["c9"], "evidence_chunks": 1},
    ]
    ratings = [
        {
            "feedback_id": 1,
            "question": "কোষ কী?",
            "sources": [
                {"chapter": "কোষ", "section": "কোষের প্রধান অংশ", "page": 1},
            ],
            "rating": -1,
            "comment": "",
            "class_level": 6,
            "message_id": "m1",
            "created_at": "2026-10-20T09:00:00",
            "comment_present": False,
            "grounded": True,
            "refused_reason": None,
        }
    ]
    candidates, notes = online_loop.build_candidates(ratings, traces, meta)
    assert len(candidates) == 1
    assert candidates[0]["trace_join"] == "citations"
    assert notes == []

    # With two traces that both fit, the rule is not exact enough: the join
    # falls to the count rule (unique by evidence_chunks) rather than guessing.
    ambiguous = [
        {"stage": "retrieval", "retrieved_ids": ["c1", "c2", "c3"], "evidence_chunks": 3},
        {"stage": "retrieval", "retrieved_ids": ["c2", "c1", "c9"], "evidence_chunks": 3},
    ]
    candidates, _ = online_loop.build_candidates(ratings, ambiguous, meta)
    assert candidates[0]["trace_join"] in ("count", "unmatched")
