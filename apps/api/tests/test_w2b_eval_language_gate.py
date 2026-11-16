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


def _counted_metrics(
    *, true_total: int, answered_true: int, false_total: int, refused_false: int
) -> SuiteMetrics:
    """Metrics carrying the raw counts the error-split report derives from."""
    return SuiteMetrics(
        total=true_total + false_total,
        grounded_rate=0.5,
        coverage_true=answered_true / true_total if true_total else 0.0,
        coverage_false=refused_false / false_total if false_total else 0.0,
        precision_true=1.0,
        faithfulness_avg=0.9,
        faithfulness_mode="local_overlap",
        grammar_avg=0.9,
        counts={
            "total": true_total + false_total,
            "matched": 0,
            "true_total": true_total,
            "answered_true": answered_true,
            "false_total": false_total,
            "refused_false": refused_false,
            "answered_total": answered_true,
        },
    )


def test_error_split_pairs_each_wilson_interval_with_its_own_denominator(capsys) -> None:
    """Unequal denominators: a swapped numerator/denominator cannot pass."""
    metrics = _counted_metrics(true_total=10, answered_true=8, false_total=5, refused_false=3)
    assert _report(metrics, None) is True
    out = capsys.readouterr().out
    # Wilson(2, 10) and Wilson(2, 5), computed independently by hand.
    assert "false_refusal=2/10 (0.2000) wilson95=[0.0567, 0.5098]" in out
    assert "false_answer=2/5 (0.4000) wilson95=[0.1176, 0.7693]" in out


def test_error_split_keeps_uncertainty_at_the_rate_extremes(capsys) -> None:
    """Zero and all-observed errors still carry an honest interval."""
    metrics = _counted_metrics(true_total=10, answered_true=10, false_total=10, refused_false=0)
    assert _report(metrics, None) is True
    out = capsys.readouterr().out
    assert "false_refusal=0/10 (0.0000) wilson95=[0.0000, 0.2775]" in out
    assert "false_answer=10/10 (1.0000) wilson95=[0.7225, 1.0000]" in out


def test_error_split_with_empty_denominators_reports_full_range(capsys) -> None:
    metrics = _counted_metrics(true_total=0, answered_true=0, false_total=0, refused_false=0)
    assert _report(metrics, None) is True
    out = capsys.readouterr().out
    assert "false_refusal=n/a wilson95=[0.0000, 1.0000]" in out
    assert "false_answer=n/a wilson95=[0.0000, 1.0000]" in out


def test_error_split_is_reporting_only_not_serialized() -> None:
    """The regression gate's contract stays byte-stable: no derived keys."""
    metrics = _counted_metrics(true_total=10, answered_true=8, false_total=5, refused_false=3)
    serialized = metrics.as_dict()
    assert "false_refusal_rate" not in serialized
    assert "false_answer_rate" not in serialized
    assert "false_refusal_wilson95" not in serialized
    assert "false_answer_wilson95" not in serialized
    assert "error_split" not in serialized
