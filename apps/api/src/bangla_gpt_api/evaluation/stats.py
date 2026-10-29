"""Evaluation statistics: intervals, paired bootstrap, latency percentiles.

RAG-20/RAG-22: a rate without an interval cannot support or reject a quality
claim, and two runs of a 400-item suite routinely differ by several points
from sampling noise alone. These helpers are stdlib-only and deliberately
small so the CLI can print honest bounds without a dependency:

* :func:`wilson` -- 95% Wilson score interval for a proportion. Preferred
  over the normal approximation because proportions here sit near 1.0 (the
  y-v2 metrics were all 1.00) where the normal interval degenerates.
* :func:`bootstrap_ci` -- percentile bootstrap of a statistic over a sample.
* :func:`paired_bootstrap` -- the same over per-item differences of two runs.
  Paired (per question), so item difficulty cancels; the result is
  "no measurable difference" when the interval spans zero.
* :func:`percentile` -- numpy-free percentile for the per-stage latency
  report (p50/p95/p99 measured on one machine, one corpus build).

The CI gate stays a fixed 2pp regression threshold; the intervals qualify the
numbers the gate prints rather than replacing the rule.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterator, Sequence

#: z for a two-sided 95% interval.
Z_95 = 1.959963984540054


def wilson(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Two-sided Wilson score interval for ``successes / total`` in [0, 1].

    ``total == 0`` has no information: the interval is the full [0, 1] range,
    which is the honest statement rather than a point estimate of zero.
    """
    if total <= 0:
        return (0.0, 1.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def _unit_stream(seed: int) -> Iterator[float]:
    """Deterministic uniform float stream from a SHA-256 DRBG.

    The bootstrap needs a reproducible resample and nothing else: this is a
    hash-based generator (counter mode over SHA-256, one digest per four
    draws), so the result is identical on every platform and Python version
    and no pseudo-random module is involved.
    """
    counter = 0
    while True:
        digest = hashlib.sha256(f"{seed}:{counter}".encode("ascii")).digest()
        for offset in range(0, 32, 8):
            yield int.from_bytes(digest[offset : offset + 8], "big") / float(1 << 64)
        counter += 1


def bootstrap_ci(
    values: Sequence[float],
    stat: Callable[[Sequence[float]], float] | None = None,
    *,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Percentile bootstrap (stat, low, high) for a statistic over ``values``.

    The resample comes from :func:`_unit_stream`, seeded by ``seed``, so the
    CLI can print the seed and a re-run reproduces the interval exactly.
    """
    if not values:
        return (0.0, 0.0, 0.0)
    mean = stat or (lambda xs: sum(xs) / len(xs))
    sample = list(values)
    size = len(sample)
    draws_source = _unit_stream(seed)
    draws = []
    for _ in range(n_boot):
        resample = [sample[int(next(draws_source) * size)] for _ in range(size)]
        draws.append(mean(resample))
    draws.sort()
    return (
        mean(sample),
        draws[int(alpha / 2 * n_boot)],
        draws[max(0, int((1 - alpha / 2) * n_boot) - 1)],
    )


def paired_bootstrap(
    baseline: Sequence[float],
    current: Sequence[float],
    *,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict:
    """Per-item difference ``current - baseline`` with a bootstrap interval.

    ``significant`` is False whenever the interval covers zero -- the case the
    report prints as "no measurable difference". Items must be aligned (same
    question order in both sequences), which is how the eval suite runs: the
    committed baseline stores one score per item.
    """
    if len(baseline) != len(current):
        raise ValueError(f"paired bootstrap needs aligned items: {len(baseline)} != {len(current)}")
    if not baseline:
        return {"n": 0, "mean_diff": 0.0, "ci_low": 0.0, "ci_high": 0.0, "significant": False}
    diffs = [float(y) - float(x) for x, y in zip(baseline, current, strict=True)]
    mean, low, high = bootstrap_ci(diffs, n_boot=n_boot, seed=seed, alpha=alpha)
    return {
        "n": len(diffs),
        "mean_diff": round(mean, 6),
        "ci_low": round(low, 6),
        "ci_high": round(high, 6),
        "significant": low > 0.0 or high < 0.0,
    }


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0, 100]); empty -> 0.0."""
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (q / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def percentile_report(values: Sequence[float], quantiles: Sequence[float] = (50, 95, 99)) -> dict:
    """``{"n": ..., "p50": ..., "p95": ..., "p99": ...}`` with rounded values."""
    return {
        "n": len(values),
        **{f"p{int(q)}": round(percentile(values, q), 3) for q in quantiles},
    }


def interval_report(successes: int, total: int, *, digits: int = 4) -> dict:
    """Proportion with its Wilson interval, in the shape the CLI prints."""
    low, high = wilson(successes, total)
    return {
        "n": total,
        "successes": successes,
        "rate": round(successes / total, digits) if total else 0.0,
        "ci95_low": round(low, digits),
        "ci95_high": round(high, digits),
    }
