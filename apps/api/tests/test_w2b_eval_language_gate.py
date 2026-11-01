"""Language-integrity legs of the eval gate (RAG-21/F-132).

The defect: the two master floors ("Assamese letters = 0", "language
consistency >= 99%") were computed and printed but never enforced -- the gate
compared six rates and an unenforced claim is not a gate. These tests pin the
legs and the unconditional RAG-D1/SLOP-D1 answer-quality label.
"""

from __future__ import annotations

from bangla_gpt_api.evaluation.cli import _report
from bangla_gpt_api.evaluation.metrics import (
    LANGUAGE_CONSISTENCY_FLOOR,
    SuiteMetrics,
    compare_gate_with_intervals,
)


def _metrics(*, consistency: float = 1.0, assamese: int = 0) -> SuiteMetrics:
    return SuiteMetrics(
        total=100,
        grounded_rate=0.9,
        coverage_true=0.9,
        coverage_false=1.0,
        precision_true=1.0,
        faithfulness_avg=0.9,
        faithfulness_mode="local_overlap",
        grammar_avg=0.9,
        language_consistency=consistency,
        assamese_letter_violations=assamese,
    )


def test_consistent_and_clean_run_passes_the_language_legs() -> None:
    passed, lines = compare_gate_with_intervals(_metrics().as_dict(), _metrics())
    assert passed
    assert any("language_consistency" in line and "PASS" in line for line in lines)
    assert any("assamese_letter_violations" in line and "PASS" in line for line in lines)


def test_assamese_letter_fails_even_without_a_rate_drop() -> None:
    passed, lines = compare_gate_with_intervals(_metrics().as_dict(), _metrics(assamese=1))
    assert not passed
    assert any("assamese_letter_violations" in line and "FAIL" in line for line in lines)


def test_consistency_floor_fails_below_99_percent() -> None:
    baseline = _metrics().as_dict()
    # 1.5pp drop is inside the 2pp band, but below the absolute floor -> FAIL.
    assert not compare_gate_with_intervals(baseline, _metrics(consistency=0.985))[0]
    # 0.5pp drop stays above the floor -> PASS.
    assert compare_gate_with_intervals(baseline, _metrics(consistency=0.995))[0]
    assert LANGUAGE_CONSISTENCY_FLOOR == 0.99


def test_floor_applies_without_a_baseline_value() -> None:
    baseline = _metrics().as_dict()
    del baseline["language_consistency"]
    passed, lines = compare_gate_with_intervals(baseline, _metrics(consistency=0.98))
    assert not passed
    assert any("language_consistency" in line and "no baseline value" in line for line in lines)


def test_report_prints_the_unverified_live_answer_quality_label(capsys) -> None:
    verdict = _report(_metrics(), None)
    assert verdict is True
    out = capsys.readouterr().out
    assert "ANSWER QUALITY (RAG-D1/SLOP-D1): UNVERIFIED-LIVE" in out
    assert "JUDGE: mode=local_overlap" in out
