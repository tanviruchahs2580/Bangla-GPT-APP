"""Ranking metrics for the honest retrieval evaluation (T-14).

Small, tested, dependency-free functions over binary-relevance ranked lists,
plus seeded bootstrap intervals. Every eval metric the harness reports carries
its ``provenance`` (T-14): ``synthetic_from_corpus`` numbers describe the
generator's own vocabulary and never support a real-world quality claim;
``synthetic_paraphrase`` and ``human`` sets are reported separately and are
never merged with anything.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence


def recall_at_k(ranked: Sequence[bool], k: int) -> float:
    """1 when a relevant item appears in the top ``k`` positions, else 0.

    Binary relevance with a single expected target per query, so recall@k
    collapses to hit@k per item; the aggregation over items is the caller's.
    An empty list answers 0.0 (nothing can be relevant).
    """
    if k <= 0:
        raise ValueError("k must be >= 1")
    if not ranked:
        return 0.0
    return 1.0 if any(ranked[:k]) else 0.0


def reciprocal_rank(ranked: Sequence[bool]) -> float:
    """1/(1-based position of the first relevant item), 0.0 when none."""
    for i, relevant in enumerate(ranked, start=1):
        if relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[bool], k: int) -> float:
    """nDCG@k with binary gains: DCG/IDCG with the standard log2 discount.

    DCG = sum over positions of gain / log2(rank + 1); with binary relevance
    and a single relevant item per query the ideal DCG is 1/log2(2) = 1, so
    nDCG@k equals DCG@k of the ranking itself.
    """
    if k <= 0:
        raise ValueError("k must be >= 1")
    dcg = sum((1.0 if r else 0.0) / math.log2(i + 2) for i, r in enumerate(ranked[:k]))
    if dcg == 0.0:
        return 0.0
    return dcg / (1.0 / math.log2(2))


def bootstrap_ci(
    values: Sequence[float],
    *,
    seed: int,
    resamples: int = 1000,
) -> tuple[float, float]:
    """Percentile bootstrap 95% CI for the mean, seeded and deterministic."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)  # noqa: S311 - deterministic eval sampling, not crypto
    n = len(values)
    means: list[float] = []
    for _ in range(max(1, resamples)):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    low = means[int(0.025 * len(means))]
    high = means[min(len(means) - 1, int(0.975 * len(means)))]
    return (low, high)


def paired_bootstrap_delta(
    current: Sequence[float],
    baseline: Sequence[float],
    *,
    seed: int,
    resamples: int = 1000,
) -> dict:
    """Paired bootstrap for mean(current - baseline) on the same items.

    Both sequences must be the same length and item-aligned; the CI is for
    the DELTA, so correlated per-item noise cancels instead of widening the
    interval the way two independent CIs would.
    """
    if len(current) != len(baseline):
        raise ValueError("paired sequences must be item-aligned")
    deltas = [c - b for c, b in zip(current, baseline, strict=True)]
    low, high = bootstrap_ci(deltas, seed=seed, resamples=resamples)
    mean = sum(deltas) / len(deltas) if deltas else 0.0
    return {"delta_mean": round(mean, 6), "ci95": [round(low, 6), round(high, 6)], "n": len(deltas)}


def rank_metrics_summary(
    relevance_lists: Sequence[Sequence[bool]],
    *,
    k_values: Sequence[int] = (1, 3, 5, 10),
    seed: int,
    resamples: int = 1000,
) -> dict:
    """Aggregate recall@k / MRR / nDCG@10 over per-item ranked relevance lists.

    ``relevance_lists[i][j]`` answers "is the j-th retrieved chunk relevant to
    query i". Each aggregate carries a seeded bootstrap 95% CI; the summary
    states ``n`` and carries the caller's provenance label.
    """
    if not relevance_lists:
        return {"n": 0, "provenance_required": True}
    recalls = {f"recall_at_{k}": [recall_at_k(r, k) for r in relevance_lists] for k in k_values}
    mrr_values = [reciprocal_rank(r) for r in relevance_lists]
    ndcg_values = [ndcg_at_k(r, 10) for r in relevance_lists]
    summary: dict = {"n": len(relevance_lists)}
    for key, vals in recalls.items():
        low, high = bootstrap_ci(vals, seed=seed, resamples=resamples)
        summary[key] = {
            "mean": round(sum(vals) / len(vals), 4),
            "ci95": [round(low, 4), round(high, 4)],
        }
    low, high = bootstrap_ci(mrr_values, seed=seed, resamples=resamples)
    summary["mrr"] = {
        "mean": round(sum(mrr_values) / len(mrr_values), 4),
        "ci95": [round(low, 4), round(high, 4)],
    }
    low, high = bootstrap_ci(ndcg_values, seed=seed, resamples=resamples)
    summary["ndcg_at_10"] = {
        "mean": round(sum(ndcg_values) / len(ndcg_values), 4),
        "ci95": [round(low, 4), round(high, 4)],
    }
    return summary
