"""Evaluation statistics -- intervals, paired bootstrap, percentiles (RAG-22).

The rule these tests pin: a rate without an interval cannot support or reject a
claim. Wilson is used because the evaluated proportions sit near 1.0, where the
normal approximation produces intervals wider than 1 or narrower than reality.
The paired bootstrap is the only comparison the CLI prints for a metric delta,
and "no measurable difference" must be the verdict whenever the interval covers
zero -- including the degenerate all-zero-difference case.
"""

from __future__ import annotations

from bangla_gpt_api.evaluation.stats import (
    bootstrap_ci,
    interval_report,
    paired_bootstrap,
    percentile,
    percentile_report,
    wilson,
)


def test_wilson_matches_the_published_worked_examples() -> None:
    low, high = wilson(0, 50)
    assert abs(low) < 1e-9  # no successes: the lower bound is zero
    assert abs(high - 0.0713) < 0.001  # zero failures in 50 samples
    low, high = wilson(45, 50)
    assert 0.78 < low < 0.80
    assert 0.95 < high < 0.97
    low, high = wilson(5, 10)
    assert 0.236 < low < 0.237
    assert 0.763 < high < 0.764


def test_wilson_with_no_samples_is_the_full_range() -> None:
    assert wilson(0, 0) == (0.0, 1.0)


def test_wilson_interval_narrows_with_n() -> None:
    small = wilson(30, 40)
    large = wilson(300, 400)
    assert small[0] < large[0] < large[1] < small[1]
    assert (30 / 40) == (300 / 400)


def test_interval_report_shape() -> None:
    report = interval_report(340, 427)
    assert report["n"] == 427
    assert report["successes"] == 340
    assert report["rate"] == 0.7963
    assert report["ci95_low"] < report["rate"] < report["ci95_high"]
    assert report["ci95_low"] > 0.7 and report["ci95_high"] < 0.85


def test_bootstrap_ci_is_seeded_and_brackets_the_mean() -> None:
    values = [1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    mean, low, high = bootstrap_ci(values, seed=7)
    assert low <= mean <= high
    assert (mean, low, high) == bootstrap_ci(values, seed=7)


def test_paired_bootstrap_detects_a_real_shift() -> None:
    baseline = [0.0] * 60
    current = [1.0] * 60
    result = paired_bootstrap(baseline, current, seed=1)
    assert result["significant"] is True
    assert result["mean_diff"] == 1.0
    assert result["ci_low"] > 0.0


def test_paired_bootstrap_calls_noise_noise() -> None:
    """A delta the interval cannot separate from zero is not an improvement."""
    baseline = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0] * 10
    current = [1.0, 1.0, 1.0, 0.0, 0.0, 1.0] * 10
    result = paired_bootstrap(baseline, current, seed=3)
    assert -0.20 <= result["mean_diff"] <= 0.20
    assert result["significant"] is False


def test_paired_bootstrap_identical_runs_are_no_difference() -> None:
    scores = [1] * 400 + [0] * 27
    result = paired_bootstrap(scores, scores, seed=20261029)
    assert result["mean_diff"] == 0.0
    assert result["significant"] is False
    assert result["n"] == len(scores)


def test_paired_bootstrap_requires_aligned_items() -> None:
    import pytest

    with pytest.raises(ValueError):
        paired_bootstrap([1, 0], [1, 0, 1])


def test_percentile_interpolates_and_handles_edges() -> None:
    values = [0.30, 0.10, 0.20, 0.40]
    assert percentile(values, 0) == 0.10
    assert percentile(values, 100) == 0.40
    assert abs(percentile(values, 50) - 0.25) < 1e-9
    assert percentile([], 50) == 0.0
    assert percentile([0.7], 99) == 0.7


def test_percentile_report_carries_p50_p95_p99() -> None:
    values = [float(i) for i in range(1, 101)]
    report = percentile_report(values)
    assert report["n"] == 100
    assert abs(report["p50"] - 50.5) < 0.01
    assert abs(report["p95"] - 95.05) < 0.06
    assert abs(report["p99"] - 99.01) < 0.06
