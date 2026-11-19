"""T-14: hand-computed fixtures for the ranking metrics and the human-set
loader. Every expected number below was computed by hand from the metric
definitions, not read back from the implementation."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from bangla_gpt_api.evaluation.retrieval_metrics import (
    bootstrap_ci,
    ndcg_at_k,
    paired_bootstrap_delta,
    rank_metrics_summary,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_hand_computed():
    ranked = [False, True, False, True]
    assert recall_at_k(ranked, 1) == 0.0  # top-1 irrelevant
    assert recall_at_k(ranked, 2) == 1.0  # relevant at position 2
    assert recall_at_k(ranked, 4) == 1.0
    assert recall_at_k([], 3) == 0.0  # nothing retrieved
    assert recall_at_k([False, False], 5) == 0.0
    with pytest.raises(ValueError):
        recall_at_k([True], 0)


def test_reciprocal_rank_hand_computed():
    assert reciprocal_rank([True]) == 1.0
    assert reciprocal_rank([False, True]) == 0.5
    assert reciprocal_rank([False, False, True]) == pytest.approx(1 / 3)
    assert reciprocal_rank([False, False]) == 0.0


def test_ndcg_at_k_hand_computed():
    # relevant at rank 1: DCG = 1/log2(2) = 1 -> nDCG = 1
    assert ndcg_at_k([True, False, False], 3) == pytest.approx(1.0)
    # relevant at rank 2: DCG = 1/log2(3) -> nDCG = log2(2)/log2(3)
    assert ndcg_at_k([False, True, False], 3) == pytest.approx(math.log2(2) / math.log2(3))
    # nothing relevant in the window
    assert ndcg_at_k([False, False], 2) == 0.0


def test_bootstrap_ci_is_seeded_and_brackets_the_mean():
    vals = [0.0] * 60 + [1.0] * 40  # mean 0.4
    lo1, hi1 = bootstrap_ci(vals, seed=42, resamples=1000)
    lo2, hi2 = bootstrap_ci(vals, seed=42, resamples=1000)
    assert (lo1, hi1) == (lo2, hi2), "same seed must reproduce the same interval"
    assert lo1 <= 0.4 <= hi1


def test_paired_bootstrap_delta_detects_an_exact_improvement():
    baseline = [0.0] * 50 + [1.0] * 50
    current = [0.0] * 50 + [1.0] * 50 + [1.0] * 0
    # make every item one better on a strict subset: delta +1 on 10 items
    current = [1.0 if i < 10 else baseline[i] for i in range(100)]
    result = paired_bootstrap_delta(current, baseline, seed=7)
    assert result["n"] == 100
    assert result["delta_mean"] == pytest.approx(0.1)
    assert result["ci95"][0] > 0.0, "a constant +0.1 delta must have a CI away from zero"


def test_paired_bootstrap_requires_alignment():
    with pytest.raises(ValueError):
        paired_bootstrap_delta([1.0, 2.0], [1.0], seed=1)


def test_rank_metrics_summary_carries_n_and_intervals():
    lists = [
        [True, False, False, False, False],  # hit at 1
        [False, True, False, False, False],  # hit at 2
        [False, False, False, False, False],  # miss
    ]
    summary = rank_metrics_summary(lists, seed=11, k_values=(1, 3, 5))
    assert summary["n"] == 3
    assert summary["recall_at_1"]["mean"] == pytest.approx(1 / 3, abs=1e-3)
    assert summary["recall_at_3"]["mean"] == pytest.approx(2 / 3, abs=1e-3)
    assert summary["recall_at_5"]["mean"] == pytest.approx(2 / 3, abs=1e-3)
    assert summary["mrr"]["mean"] == pytest.approx((1.0 + 0.5 + 0.0) / 3, abs=1e-3)
    # every aggregate carries an interval
    for key in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr", "ndcg_at_10"):
        assert len(summary[key]["ci95"]) == 2


def test_rank_metrics_summary_empty_is_explicit():
    summary = rank_metrics_summary([], seed=1)
    assert summary == {"n": 0, "provenance_required": True}


def test_human_eval_loader_round_trip(tmp_path: Path):
    from bangla_gpt_api.evaluation.human_eval import human_set_status, load_human_eval

    data = {
        "provenance": "human",
        "items": [
            {
                "query": "kap?er bocoroner byapak",
                "expected_chunk_ids": ["nctb-secondary-0001"],
                "class_level": 6,
                "subject": "science",
                "annotator_id": "teacher-01",
                "date": "2026-11-20",
            }
        ],
    }
    path = tmp_path / "human_eval.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_human_eval(path)
    assert loaded["provenance"] == "human"
    assert len(loaded["items"]) == 1
    status, n = human_set_status(path, min_items=300)
    assert n == 1
    assert status == "present-below-minimum"

    missing_status, missing_n = human_set_status(tmp_path / "absent.json", min_items=300)
    assert (missing_status, missing_n) == ("absent", 0)


def test_human_eval_loader_rejects_unknown_provenance(tmp_path: Path):
    from bangla_gpt_api.evaluation.human_eval import load_human_eval

    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps({"provenance": "synthetic_from_corpus", "items": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_human_eval(path)
