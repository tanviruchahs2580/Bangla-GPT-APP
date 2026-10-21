"""A8-08: the generation report carries confidence intervals, not just rates.

The item's verification line is "results versus targets with CIs". A target
like "false refusal on answerable <= 5%" cannot be read off a bare point
estimate on 181 items, and several of the rates here sit at or near zero
successes -- exactly where the normal approximation is wrong. The report
therefore carries a 95% Wilson score interval per proportion.

These tests pin the interval itself (against the published values for the
small-sample edge cases) and the report contract (every gated rate has an
entry with the trials and successes it came from).
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.evaluation.generation import generation_metrics, wilson_interval


def test_wilson_bounds_the_published_edge_cases() -> None:
    """0/10 -> [0, 0.2775] and 10/10 -> [0.7225, 1] are the textbook values."""
    assert wilson_interval(0, 10) == [0.0, 0.2775]
    assert wilson_interval(10, 10) == [0.7225, 1.0]
    low, high = wilson_interval(5, 10)
    assert low == pytest.approx(0.2366, abs=5e-4)
    assert high == pytest.approx(0.7634, abs=5e-4)


def test_wilson_has_no_interval_without_trials() -> None:
    assert wilson_interval(0, 0) is None


def test_intervals_stay_inside_the_unit_interval() -> None:
    for successes, trials in ((0, 22), (22, 22), (1, 185), (184, 185)):
        low, high = wilson_interval(successes, trials)
        assert 0.0 <= low <= high <= 1.0


def test_every_gated_rate_carries_its_interval() -> None:
    """The report's intervals_95 covers each rate the replay gate compares."""
    rows = [
        {"expect": "answer", "grounded": True, "answer": "উত্তর", "sources": []},
        {"expect": "refuse", "grounded": False, "answer": "", "sources": []},
    ]
    metrics = generation_metrics(rows)
    intervals = metrics["intervals_95"]
    for key in (
        "citation_precision",
        "citation_recall",
        "abstention_precision",
        "abstention_recall",
        "false_refusal_rate",
        "refusal_correctness_unsafe",
        "response_language_correctness",
        "format_validity",
    ):
        entry = intervals[key]
        assert entry["n"] >= 0 and entry["successes"] >= 0, key
        # An empty denominator is the one case with no interval to report.
        assert (entry["ci"] is None) == (entry["n"] == 0), key
    assert intervals["false_refusal_rate"]["n"] == 1
