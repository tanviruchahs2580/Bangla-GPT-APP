"""A4-01/A4-02/A4-07: the variant matrix is real, seeded and complete.

These tests pin the properties the audit's A4-01 finding needed: every
required variant is a separately reported row, the metrics carry CIs, the
top-k curve is a measured recall-versus-context-cost pair, and the report is
deterministic apart from the labelled latency.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bangla_gpt_api.evaluation import variant_matrix

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "golden_v2.json"


@pytest.fixture(scope="module")
def report() -> dict:
    return variant_matrix.build_report(golden_path=GOLDEN, split="test", seed=20261019)


def test_every_required_variant_is_reported(report: dict) -> None:
    """A4-01 asks for lexical, dense, fusion and rerank-off rows; all exist."""
    assert set(report["variants"]) == {
        "lexical",
        "dense",
        "hybrid_rerank_off",
        "hybrid_served",
        "hybrid_mmr",
    }
    for name, block in report["variants"].items():
        for metric in ("recall_at_1", "recall_at_3", "recall_at_5", "recall_at_10", "mrr_at_10"):
            assert metric in block, f"{name} missing {metric}"
        assert block["n"] > 0


def test_cis_bracket_each_headline_metric(report: dict) -> None:
    for block in report["variants"].values():
        for metric in ("recall_at_1", "recall_at_5", "mrr_at_10"):
            low, high = block[f"{metric}_ci95"]
            assert low <= block[metric] <= high, metric


def test_recall_is_monotone_in_k(report: dict) -> None:
    for block in report["variants"].values():
        assert block["recall_at_1"] <= block["recall_at_3"] <= block["recall_at_5"]
        assert block["recall_at_5"] <= block["recall_at_10"]


def test_report_is_seeded_and_split_scoped(report: dict) -> None:
    conditions = report["run_conditions"]
    assert conditions["split"] == "test"
    assert conditions["seed"] == 20261019
    assert conditions["positive_items"] == report["variants"]["hybrid_served"]["n"]
    again = variant_matrix.build_report(golden_path=GOLDEN, split="test", seed=20261019)
    for name in report["variants"]:
        assert report["variants"][name]["recall_at_5"] == again["variants"][name]["recall_at_5"]
        assert (
            report["variants"][name]["mrr_at_10_ci95"] == again["variants"][name]["mrr_at_10_ci95"]
        )


def test_top_k_curve_pairs_recall_with_context_cost(report: dict) -> None:
    """A4-07: top-k is read from a recall-versus-cost curve, not by fiat."""
    curve = report["top_k_curve"]["curve"]
    assert set(curve) == {str(k) for k in range(1, 11)}
    recalls = [curve[str(k)]["recall"] for k in range(1, 11)]
    assert recalls == sorted(recalls), "recall must be non-decreasing in k"
    costs = [curve[str(k)]["mean_context_chars"] for k in range(1, 11)]
    assert costs == sorted(costs), "context cost must be non-decreasing in k"
    assert all(curve[str(k)]["mean_context_tokens_est"] > 0 for k in range(1, 11))
    assert report["top_k_curve"]["chosen_top_k"] == 3


def test_paired_mde_is_reported_against_the_served_lane(report: dict) -> None:
    paired = report["paired_mde_vs_served"]
    assert set(paired) == {
        "hybrid_served_vs_lexical",
        "hybrid_served_vs_dense",
        "hybrid_served_vs_hybrid_rerank_off",
        "hybrid_served_vs_hybrid_mmr",
    }
    assert all(value is None or value >= 0 for value in paired.values())


def test_unmeasured_variants_carry_their_reason(report: dict) -> None:
    """A cross-encoder row would be a fabricated number; it must say so."""
    assert "cross_encoder_rerank" in report["not_measured"]
    assert "weights" in report["not_measured"]["cross_encoder_rerank"]
    markdown = variant_matrix.markdown_summary(report)
    assert "hybrid_served" in markdown and "Recall@5" in markdown


def test_rerank_off_is_the_documented_fallback_ranking(report: dict) -> None:
    """A4-08: the rerank-off row is the ranking serving falls back to."""
    candidates = [(object(), 0.5, 0.25)]
    assert variant_matrix.rrf_only_rerank("q", candidates) == [0.75]
    assert "hybrid_rerank_off" in report["variants"]
