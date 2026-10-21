"""A8-03 / AUD-A2-12: per-stratum retrieval metrics with 95% bootstrap CIs.

The audit's status for A8-03 was FAIL because retrieval was reported as three
hand-picked query families with no confidence intervals, no rank-weighted
metric on the *golden* set, no filtered-versus-unfiltered comparison and no
statement of what a sample of that size can even detect. A metric without a CI
invites reading sampling noise as a regression; a CI without an MDE invites
pre-registering a tolerance smaller than the sample can measure.

This module is the metric layer, kept free of I/O so the numbers are unit
testable on ranks whose values are known by construction:

* :func:`per_query_values` -- the per-query 0/1 (or graded) value of each
  metric, the unit the bootstrap resamples and the MDE is computed from;
* :func:`metrics_block` -- Recall@1/3/5/10, MRR@10, nDCG@10 and hit-rate@10
  with a seeded percentile 95% bootstrap CI for every one of them;
* :func:`minimum_detectable_effect` -- the smallest true change this sample
  can distinguish from noise at 95% confidence and 80% power, for a paired
  comparison (two runs on the same queries, e.g. filtered vs unfiltered) and
  for an absolute one-sample reading.

Definitions are pinned by tests, not by this docstring: see
``tests/test_eval2_strata.py``.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Iterable

#: Bootstrap resamples per CI. 1000 keeps a full stratified report under a
#: minute of CPU while the percentile interval is stable to ~0.005.
BOOTSTRAP_RESAMPLES = 1000

#: Per-stratum CIs use fewer resamples than the overall block: a full report
#: holds ~25 strata x 2 lanes x 7 metrics, and at 1000 resamples that alone
#: cost ~50 s of the command's runtime. Measured on the committed sample the
#: 250-resample percentile edge is within 0.01 of the 1000-resample edge
#: (pinned by tests/test_eval2_strata.py on a 200-query sample); the overall
#: block -- the one a decision reads -- keeps the full 1000.
STRATA_RESAMPLES = 250

#: Two-sided 95% CI and 80% power multipliers (standard normal quantiles).
#: The MDE for a difference of means is ``(z_ci + z_power) * sd / sqrt(n)``
#: -- the inverted form of the usual sample-size relation
#: ``n = (z_ci + z_power)^2 * sd^2 / mde^2``. Values are the standard
#: quantiles (1.959964 for 0.975, 0.841621 for 0.80), stated here so the
#: report can be recomputed by hand.
Z_CI95 = 1.959963984540054
Z_POWER80 = 0.8416212335729143

#: A stratum below this n reports metrics and CIs but no MDE: with n < 5 the
#: sample standard deviation is dominated by which queries happened to land
#: in the stratum, and quoting an MDE from it would be a fabricated number.
MIN_MDE_N = 5

#: Metric names in report order, each mapped to (k, kind).
METRIC_SPECS: dict[str, tuple[int, str]] = {
    "recall_at_1": (1, "recall"),
    "recall_at_3": (3, "recall"),
    "recall_at_5": (5, "recall"),
    "recall_at_10": (10, "recall"),
    "mrr_at_10": (10, "mrr"),
    "ndcg_at_10": (10, "ndcg"),
    "hit_rate_at_10": (10, "hit"),
}

#: The pre-registered primary retrieval metric (docs/evaluation/pre-registration.md).
PRIMARY_METRIC = "recall_at_5"


def metrics_from_ranks(ranks: Iterable[int]) -> tuple[dict[str, list[float]], int]:
    """Per-query values for every metric; rank 0 means "not retrieved in top-k".

    Returns ``(values_by_metric, n)``. ``hit_rate_at_10`` is "at least one
    wanted evidence unit in the top-10"; with the single-unit gold sets the
    golden evaluator uses it coincides with ``recall_at_10`` by construction,
    and both are reported so a future multi-unit gold set cannot silently
    change one without the other.
    """
    ranks = list(ranks)
    values: dict[str, list[float]] = {}
    for name, (k, kind) in METRIC_SPECS.items():
        if kind == "recall":
            values[name] = [1.0 if 0 < rank <= k else 0.0 for rank in ranks]
        elif kind == "mrr":
            values[name] = [1.0 / rank if 0 < rank <= k else 0.0 for rank in ranks]
        elif kind == "ndcg":
            # Binary relevance, one wanted unit: IDCG is 1 (a hit at rank 1),
            # so a hit at rank r contributes 1/log2(r+1).
            values[name] = [1.0 / math.log2(rank + 1) if 0 < rank <= k else 0.0 for rank in ranks]
        else:  # hit
            values[name] = [1.0 if 0 < rank <= k else 0.0 for rank in ranks]
    return values, len(ranks)


def mean(values: list[float]) -> float:
    """Arithmetic mean at report precision; empty -> 0.0 (never NaN)."""
    return round(sum(values) / len(values), 4) if values else 0.0


def bootstrap_ci_mean(
    values: list[float], *, seed: int, resamples: int = BOOTSTRAP_RESAMPLES
) -> list[float]:
    """Percentile 95% CI of the mean by resampling queries with replacement.

    Seeded, so two runs over the same ranks print identical intervals -- a CI
    that wobbles between runs of the same data is itself noise.
    """
    return _bootstrap_ci_means({"metric": values}, seed=seed, resamples=resamples)["metric"]


def _bootstrap_ci_means(
    values_by_metric: dict[str, list[float]],
    *,
    seed: int,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, list[float]]:
    """Percentile 95% CIs for several metrics over the same query sample.

    Resampling is by *value bucket*, not by query: the resampled mean of n
    draws from the empirical distribution is ``Σ value·count / n`` over the
    distinct values with their multinomial counts, and every metric here has
    at most a handful of distinct values (binary recalls, 11 rank buckets for
    MRR/nDCG). That turns the naive 1000 x n x metrics loop into a 1000 x
    buckets one -- the same numbers, ~30x faster, which is what makes a fully
    stratified report a CI-able command rather than a coffee break.
    """
    n = len(next(iter(values_by_metric.values()))) if values_by_metric else 0
    if n == 0:
        return {name: [0.0, 0.0] for name in values_by_metric}
    rng = random.Random(seed)  # noqa: S311 - resampling, not security
    buckets: dict[str, tuple[list[float], list[int]]] = {}
    for name, values in values_by_metric.items():
        counts = Counter(values)
        buckets[name] = (list(counts), [counts[v] for v in counts])
    dists: dict[str, list[float]] = {name: [] for name in values_by_metric}
    for _ in range(resamples):
        for name, (values_, weights) in buckets.items():
            drawn = Counter(rng.choices(values_, weights=weights, k=n))
            dists[name].append(sum(v * c for v, c in drawn.items()) / n)
    out: dict[str, list[float]] = {}
    for name, dist in dists.items():
        dist.sort()
        out[name] = [
            round(dist[int(0.025 * resamples)], 4),
            round(dist[int(0.975 * resamples)], 4),
        ]
    return out


def sample_sd(values: list[float]) -> float:
    """Sample standard deviation (ddof=1); 0.0 for n < 2 (undefined, not 0)."""
    n = len(values)
    if n < 2:
        return 0.0
    mu = sum(values) / n
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def minimum_detectable_effect(sd: float, n: int) -> float | None:
    """Smallest detectable difference of means at 95% CI / 80% power.

    ``None`` for n < :data:`MIN_MDE_N`: below that the sd is not estimable
    enough to publish a number, and silence is the honest answer.
    """
    if n < MIN_MDE_N:
        return None
    return round((Z_CI95 + Z_POWER80) * sd / math.sqrt(n), 4)


def paired_mde(values_a: list[float], values_b: list[float]) -> float | None:
    """MDE for a paired comparison (same queries in both runs).

    Pairs by position, which is why both lists must come from the same query
    order -- the caller guarantees that by construction. Pairing removes the
    query-difficulty variance that dominates the unpaired reading; this is the
    number a filtered-vs-unfiltered (or before-vs-after) decision should use.
    """
    if len(values_a) != len(values_b) or len(values_a) < MIN_MDE_N:
        return None
    diffs = [a - b for a, b in zip(values_a, values_b, strict=True)]
    return minimum_detectable_effect(sample_sd(diffs), len(diffs))


def metrics_block(
    ranks: list[int], *, seed: int, resamples: int = BOOTSTRAP_RESAMPLES
) -> dict[str, object]:
    """Every metric with its mean, CI and the MDE the sample size buys."""
    values, n = metrics_from_ranks(ranks)
    cis = _bootstrap_ci_means(values, seed=seed, resamples=resamples)
    block: dict[str, object] = {"n": n, "bootstrap_resamples": resamples}
    for name, per_query in values.items():
        block[name] = mean(per_query)
        block[f"{name}_ci95"] = cis[name]
    block["mde_by_metric"] = {
        name: minimum_detectable_effect(sample_sd(per_query), n)
        for name, per_query in values.items()
    }
    primary_sd = sample_sd(values[PRIMARY_METRIC])
    block["mde_absolute"] = minimum_detectable_effect(primary_sd, n)
    block["mde_basis"] = PRIMARY_METRIC
    # Zero observed variance (every query at the metric's ceiling/floor) makes
    # the MDE degenerate at 0.0 -- a number nobody should read as "any change
    # is detectable". Flag it so the report cannot be misread.
    block["mde_degenerate_ceiling"] = primary_sd == 0.0 and n > 0
    block["misses"] = sum(1 for rank in ranks if rank == 0)
    return block


def strata_report(
    outcomes: list[dict[str, object]],
    *,
    keys: tuple[str, ...],
    seed: int,
) -> dict[str, dict[str, dict[str, object]]]:
    """Metrics per stratum value for each grouping key and each lane.

    ``outcomes`` rows carry the grouping fields plus ``rank_filtered`` and
    ``rank_unfiltered``. Returns ``{key: {stratum: {"filtered": block,
    "unfiltered": block, "filtered_vs_unfiltered_mde": float | None}}}``.

    The paired MDE answers the question the filtered/unfiltered split exists
    for: "does the class+subject pre-filter change Recall@5 by more than this
    sample can resolve?" -- the primary metric's per-query values are paired
    positionally, so the order must be identical across the two lanes.
    """
    report: dict[str, dict[str, dict[str, object]]] = {}
    for key in keys:
        groups: dict[str, list[dict[str, object]]] = {}
        for row in outcomes:
            groups.setdefault(str(row[key]), []).append(row)
        report[key] = {}
        for value, rows in sorted(groups.items()):
            ranks_filtered = [int(str(r["rank_filtered"])) for r in rows]
            ranks_unfiltered = [int(str(r["rank_unfiltered"])) for r in rows]
            # Strata use the cheaper resample count (STRATA_RESAMPLES) so the
            # whole report stays a ~1-minute command; the count is recorded
            # inside each block.
            filtered_block = metrics_block(ranks_filtered, seed=seed, resamples=STRATA_RESAMPLES)
            unfiltered_block = metrics_block(
                ranks_unfiltered, seed=seed, resamples=STRATA_RESAMPLES
            )
            values_f, _ = metrics_from_ranks(ranks_filtered)
            values_u, _ = metrics_from_ranks(ranks_unfiltered)
            report[key][value] = {
                "filtered": filtered_block,
                "unfiltered": unfiltered_block,
                "filtered_vs_unfiltered_mde": paired_mde(
                    values_f[PRIMARY_METRIC], values_u[PRIMARY_METRIC]
                ),
            }
    return report
