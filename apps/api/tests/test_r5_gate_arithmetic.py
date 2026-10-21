"""E-04: the grounding gate's arithmetic and its trace record, pinned.

Written after a mutmut run over the tutor's retrieval seam measured **151 of
296 mutants killed (51 %)** with the survivors concentrated in two places:

* ``_trace_retrieval`` (52 survivors): the *fields* of the per-stage trace
  record — nothing asserted them, so any mutation of a field name, a rounding
  step or the gate label survived;
* the gate arithmetic (``_in_corpus_gate_terms`` 19, ``_best_hit_coverage`` 14,
  ``_term_covered`` 8, ``_coverage_details`` 3, ``_gate_query_terms`` 3): the
  existing tests assert *verdicts* on realistic questions, so a mutation that
  changes a number without flipping a verdict (a threshold comparison, a
  weight, a rounding) survived.

These tests pin the numbers and the payload, not just the outcomes. They are
the test-strengthening half of the mutation exercise, and the mutation run is
re-measured after them.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.services.tutor import retrieval as gate
from bangla_gpt_api.services.tutor.retrieval import TutorRetrievalMixin


class _Stats:
    """document_frequency stand-in: only the terms the corpus knows."""

    def __init__(self, known: dict[str, int]) -> None:
        self._known = known
        self.total_documents = 100

    def document_frequency(self, term: str) -> int:
        return self._known.get(term, 0)


class _Meta:
    """What `bm25.indexable_text` reads off a chunk: the stamped structure."""

    def __init__(self) -> None:
        self.section = ""
        self.chapter = ""
        self.subject = None
        self.class_level = None


class _Chunk:
    def __init__(self, text: str, chunk_id: str = "c1") -> None:
        self.text = text
        self.id = chunk_id
        self.meta = _Meta()


class _Hit:
    def __init__(self, text: str, score: float, chunk_id: str = "c1") -> None:
        self.chunk = _Chunk(text, chunk_id)
        self.score = score


class _Gate(TutorRetrievalMixin):
    """The mixin with only the attributes the gate reads."""

    def __init__(self, stats: _Stats | None, min_coverage: float = 0.5) -> None:  # noqa: D107
        self.index = None
        self.provider = None
        self.fast_provider = None
        self.term_stats = stats
        self.min_score = 0.0
        self.min_coverage = min_coverage
        self.top_k = 3
        self.index_version = "fp"
        self._breaker = None
        self._fallback = None
        self._router = None


def test_out_of_domain_rule_is_the_majority_form() -> None:
    """absent > known refuses; absent == known does not (the rule is strict)."""
    service = _Gate(_Stats({"কোষ": 5}))
    _terms, refuse = service._in_corpus_gate_terms(("ইউক্লিড", "স্বতঃসিদ্ধ"))
    assert refuse is True, "two terms the corpus has never seen are out of domain"

    # Tie: one known, one unknown -> the weighted evidence decides, not the rule.
    kept, refuse = service._in_corpus_gate_terms(("ইউক্লিড", "কোষ"))
    assert refuse is False
    assert kept == ("কোষ",), "the unknown term is dropped, the known one is kept"


def test_all_terms_absent_is_the_same_refusal() -> None:
    service = _Gate(_Stats({"কোষ": 5}))
    kept, refuse = service._in_corpus_gate_terms(("ক্রিকেট", "টেস্ট"))
    assert refuse is True and kept == ()


def test_no_term_statistics_never_refuses_on_unknown_terms() -> None:
    """Without df data the rule cannot run: terms pass through unmeasured."""
    service = _Gate(None)
    kept, refuse = service._in_corpus_gate_terms(("ইউক্লিড", "স্বতঃসিদ্ধ"))
    assert refuse is False
    assert kept == ("ইউক্লিড", "স্বতঃসিদ্ধ")


def test_best_hit_coverage_reports_the_maximum_over_all_hits() -> None:
    service = _Gate(None, min_coverage=0.5)
    hits = [_Hit("অণু পরমাণু", 1.0, "a"), _Hit("অণু", 1.0, "b")]
    best, passed = service._best_hit_coverage(("অণু", "পরমাণু"), hits)
    assert passed is True
    assert best == 1.0, "coverage is the best chunk's, not the first chunk's"


def test_best_hit_coverage_requires_both_threshold_and_score() -> None:
    """A chunk under the coverage floor, or at a zero score, does not pass."""
    service = _Gate(None, min_coverage=0.6)
    assert service._best_hit_coverage(("অণু", "পরমাণু"), [_Hit("অণু", 1.0)])[1] is False
    service = _Gate(None, min_coverage=0.5)
    service.min_score = 0.5
    assert service._best_hit_coverage(("অণু",), [_Hit("অণু", 0.4)])[1] is False
    assert service._best_hit_coverage(("অণু",), [_Hit("অণু", 0.6)])[1] is True


def test_coverage_details_short_circuits_without_terms_or_hits() -> None:
    service = _Gate(_Stats({"কোষ": 5}))
    assert service._coverage_details("কোষ কী?", []) == (0.0, False)
    assert service._coverage_details("", [_Hit("কোষ", 1.0)]) == (0.0, False)


def test_term_covered_allows_one_near_match_and_nothing_further() -> None:
    """The trigram allowance is bounded: near-identical tokens only."""
    service = _Gate(None)
    assert service._term_covered("সালোকসংশ্লেষণ", {"সালোকসংশ্লেষণ"}) is True
    # One dropped conjunct: similarity ~0.75, above the 0.6 floor.
    assert service._term_covered("সালোকসংশ্লেষণ", {"সালোকসংশ্লেষ"}) is True
    # A different word of similar length: far below the floor.
    assert service._term_covered("সালোকসংশ্লেষণ", {"পরীক্ষাগার"}) is False
    # Length gate: a candidate more than three characters away is skipped.
    assert service._term_covered("অণু", {"অণুপরমাণুরতত্ত্ব"}) is False


def test_trace_retrieval_records_the_incident_fields(monkeypatch) -> None:
    """Every field of the retrieval trace record, with its own value."""
    service = _Gate(_Stats({"কোষ": 5}))
    service.index_version = "corpus-fp"
    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        gate, "trace_event", lambda event, **fields: captured.append((event, fields))
    )
    hits = [_Hit("কোষ প্রভাবক", 1.23456, "chunk-a"), _Hit("কোষ", 0.5, "chunk-b")]
    service._trace_retrieval(
        hits,
        retrieval_ms=7,
        coverage=0.8312,
        gate_pass=False,
        stream=True,
        filters={"class_level": 6, "subject": "science"},
    )
    assert len(captured) == 1
    event, fields = captured[0]
    assert event == "retrieval"
    assert fields == {
        "stream": True,
        "retrieval_ms": 7,
        "evidence_chunks": 2,
        "top_score": 1.2346,
        "scores": [1.2346, 0.5],
        "filters": {"class_level": 6, "subject": "science"},
        "coverage": 0.8312,
        "gate": "refuse",
        "index_version": "corpus-fp",
        "retrieved_ids": ["chunk-a", "chunk-b"],
    }


def test_trace_retrieval_without_hits_reports_nulls(monkeypatch) -> None:
    service = _Gate(None)
    captured: list[dict] = []
    # monkeypatch, not a hand-rolled set/delete: a hard `del` here outlives the
    # test and breaks whichever trace test the runner schedules next.
    monkeypatch.setattr(gate, "trace_event", lambda event, **fields: captured.append(fields))
    service._trace_retrieval([], retrieval_ms=0, coverage=0.0, gate_pass=True)
    fields = captured[0]
    assert fields["evidence_chunks"] == 0
    assert fields["top_score"] is None
    assert fields["scores"] == []
    assert fields["gate"] == "pass"


@pytest.mark.parametrize("question", ["কোষ কী?", "কোষ"])
def test_gate_query_terms_drops_stop_words(question: str) -> None:
    service = _Gate(None)
    assert "কোষ" in service._gate_query_terms(question)
    assert "কী?" not in service._gate_query_terms(question)
