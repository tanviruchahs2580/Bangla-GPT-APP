"""A8-03 / AUD-A2-12: the stratified retrieval metric layer and its report.

Pins the definitions (per-query values, percentile bootstrap CI, MDE) on ranks
whose values are known by construction, the resample-count choice the report
makes for cost, and the committed artifact's tie to the committed golden set.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from bangla_gpt_api.evaluation import retrieval_strata as rs

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "strata_report.py"
COMMITTED = Path(__file__).resolve().parents[1] / "eval" / "strata_report.json"
GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "golden_v2.json"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("strata_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_per_query_values_follow_the_rank_definitions() -> None:
    values, n = rs.metrics_from_ranks([1, 2, 10, 11, 0])
    assert n == 5
    assert values["recall_at_1"] == [1.0, 0.0, 0.0, 0.0, 0.0]
    assert values["recall_at_3"] == [1.0, 1.0, 0.0, 0.0, 0.0]
    assert values["recall_at_10"] == [1.0, 1.0, 1.0, 0.0, 0.0]
    assert values["mrr_at_10"] == [1.0, 0.5, 0.1, 0.0, 0.0]
    assert values["ndcg_at_10"][2] == pytest.approx(1 / 3.4594316186372978)
    assert values["hit_rate_at_10"] == values["recall_at_10"], "single-unit gold set"


def test_bootstrap_ci_brackets_the_mean_and_is_seeded() -> None:
    values = [1.0] * 82 + [0.0] * 18
    low, high = rs.bootstrap_ci_mean(values, seed=11)
    assert low <= sum(values) / len(values) <= high
    assert rs.bootstrap_ci_mean(values, seed=11) == [low, high], "seeded => reproducible"
    assert rs.bootstrap_ci_mean([], seed=11) == [0.0, 0.0]
    assert rs.bootstrap_ci_mean([0.5] * 40, seed=11) == [0.5, 0.5]


def test_fewer_strata_resamples_stay_close_to_the_full_interval() -> None:
    """STRATA_RESAMPLES is a documented cost/precision trade, not a silent neck.

    On a 200-query binary sample both CI edges must stay within 0.02 of the
    1000-resample interval -- the width of the metric's own reporting
    precision -- so a stratum CI is still read the same way.
    """
    values = [1.0] * 170 + [0.0] * 30
    full = rs.bootstrap_ci_mean(values, seed=5)
    cheap = rs.bootstrap_ci_mean(values, seed=5, resamples=rs.STRATA_RESAMPLES)
    assert abs(cheap[0] - full[0]) <= 0.02
    assert abs(cheap[1] - full[1]) <= 0.02


def test_mde_scales_with_sd_and_shrinks_with_n() -> None:
    assert rs.minimum_detectable_effect(1.0, 4) is None, "n < MIN_MDE_N is not estimable"
    per_5 = rs.minimum_detectable_effect(1.0, 5)
    per_20 = rs.minimum_detectable_effect(1.0, 20)
    assert per_5 is not None and per_20 is not None
    assert per_20 == pytest.approx(per_5 / 2, rel=0.01), "MDE ~ 1/sqrt(n)"
    assert rs.minimum_detectable_effect(0.0, 100) == 0.0


def test_paired_mde_removes_query_difficulty_variance() -> None:
    hard = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
    assert rs.paired_mde(hard, list(hard)) == 0.0, "identical runs differ by nothing"
    # A uniform +0.1 shift on the same queries is exactly resolvable when
    # paired; the unpaired reading (sd of the metric, not of the diff) cannot
    # see it at this n. Same queries, same two runs -- that is the point.
    paired = rs.paired_mde(hard, [value + 0.1 for value in hard])
    unpaired = rs.minimum_detectable_effect(rs.sample_sd(hard), len(hard))
    assert paired == 0.0
    assert unpaired is not None and unpaired > 0.3


def test_strata_report_pairs_the_two_lanes_by_item_order() -> None:
    outcomes = [
        {"class_level": 6, "rank_filtered": 1, "rank_unfiltered": 4},
        {"class_level": 6, "rank_filtered": 2, "rank_unfiltered": 0},
        {"class_level": 7, "rank_filtered": 1, "rank_unfiltered": 1},
        {"class_level": 7, "rank_filtered": 1, "rank_unfiltered": 1},
        {"class_level": 7, "rank_filtered": 1, "rank_unfiltered": 1},
        {"class_level": 7, "rank_filtered": 1, "rank_unfiltered": 1},
        {"class_level": 7, "rank_filtered": 1, "rank_unfiltered": 1},
    ]
    report = rs.strata_report(outcomes, keys=("class_level",), seed=3)
    assert set(report) == {"class_level"}
    assert set(report["class_level"]) == {"6", "7"}
    six = report["class_level"]["6"]
    assert six["filtered"]["n"] == 2
    assert six["filtered"]["recall_at_1"] == 0.5
    assert six["unfiltered"]["recall_at_1"] == 0.0
    # n=2 < MIN_MDE_N -> the paired MDE is withheld rather than fabricated
    assert six["filtered_vs_unfiltered_mde"] is None
    seven = report["class_level"]["7"]
    assert seven["filtered"]["n"] == 5


def test_committed_report_is_tied_to_the_committed_golden_set() -> None:
    report = json.loads(COMMITTED.read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    conditions = report["run_conditions"]
    positives = sum(1 for item in golden["items"] if item["expect"] == "answer")
    assert conditions["golden_dataset_hash"] == golden["dataset_hash"]
    assert conditions["golden_test_split_hash"] == golden["test_split_hash"]
    assert conditions["positive_items"] == positives
    assert conditions["gold_unmatched_items"] == 0, "every golden section resolves in the corpus"
    assert report["primary_metric"] == rs.PRIMARY_METRIC
    assert set(report["strata"]) == {"class_level", "subject", "stratum", "split"}
    assert set(report["overall"]["filtered"]) >= set(rs.METRIC_SPECS)
    for stratum in report["strata"]["class_level"].values():
        assert stratum["filtered"]["bootstrap_resamples"] == rs.STRATA_RESAMPLES
        assert stratum["unfiltered"]["bootstrap_resamples"] == rs.STRATA_RESAMPLES
    assert report["overall"]["filtered"]["bootstrap_resamples"] == rs.BOOTSTRAP_RESAMPLES
    # the sample-corpus ceiling must be visible, not implied
    assert report["overall"]["filtered"]["mde_degenerate_ceiling"] is True


def test_report_is_deterministic_on_a_golden_subset(tmp_path: Path) -> None:
    module = _load_script()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    subset = {**golden, "items": golden["items"][:12]}
    golden_path = tmp_path / "subset_golden.json"
    golden_path.write_text(json.dumps(subset, ensure_ascii=False), encoding="utf-8")
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    argv = sys.argv
    sys.argv = ["strata_report.py"]
    try:
        assert module.main(["--golden", str(golden_path), "--out", str(out_a)]) == 0
        assert module.main(["--golden", str(golden_path), "--out", str(out_b)]) == 0
    finally:
        sys.argv = argv
    first = out_a.read_text(encoding="utf-8")
    assert first == out_b.read_text(encoding="utf-8"), "seeded report must be byte-stable"
    report = json.loads(first)
    assert report["run_conditions"]["seed"] == module.DEFAULT_SEED
    assert report["run_conditions"]["positive_items"] == 12
    assert "filtered_vs_unfiltered_mde" in report["overall"]


def test_markdown_summary_has_one_row_per_class() -> None:
    module = _load_script()
    report = json.loads(COMMITTED.read_text(encoding="utf-8"))
    table = module.markdown_summary(report)
    rows = [line for line in table.splitlines() if line.startswith("|")]
    classes = set(report["strata"]["class_level"])
    assert len(rows) == 2 + 1 + len(classes), "header + separator + overall + one per class"
    for value in classes:
        assert f"| class {value} |" in table
