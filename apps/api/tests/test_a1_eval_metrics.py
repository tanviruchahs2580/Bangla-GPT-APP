"""A4-01/A1-15/A1-19/A1-20/A1-22: the extended retrieval-evaluation harness.

The audit's A4-01 status was "PARTIAL: still missing 3 of 5 variants, recall@3
/@10, nDCG@10, bootstrap CIs, latency conditions". These tests pin each of
those additions on a synthetic corpus, where the expected ranks are known by
construction rather than read off the artifact.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import ModuleType

import pytest

from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.extract import PageText

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_nctb_retrieval.py"

CELL = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক। " * 8
NEWTON = "নিউটনের প্রথম সূত্র অনুযায়ী গতির অবস্থা পরিবর্তনে বাহ্যিক বল প্রয়োজন। " * 8
PHOTO = "সালোকসংশ্লেষণ প্রক্রিয়ায় উদ্ভিদ সূর্যের আলো ব্যবহার করে খাদ্য তৈরি করে। " * 8


def _write_synthetic_corpus(target: Path) -> None:
    pages = [
        PageText(1, "অধ্যায়: কোষ\n" + CELL),
        PageText(2, "অধ্যায়: বল ও গতি\n" + NEWTON),
        PageText(3, "অধ্যায়: উদ্ভিদ\n" + PHOTO),
    ]
    chunks = chunk_pages(pages, source_id="synthetic-nctb")
    normalized = target / "normalized"
    normalized.mkdir(parents=True)
    with (normalized / "synthetic-nctb.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    (target / "quality_report.json").write_text(
        json.dumps(
            {
                "synthetic-nctb": {
                    "level": "secondary",
                    "subject_bn": "বিজ্ঞান শাখার বিষয়সমূহ",
                    "curriculum_year": "2012",
                    "bangla_char_ratio_on_usable": 0.9,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evaluate_nctb_retrieval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def synthetic_report(tmp_path_factory) -> dict:
    corpus = tmp_path_factory.mktemp("nctb-eval") / "nctb"
    _write_synthetic_corpus(corpus)
    module = _load_script()
    argv = sys.argv
    sys.argv = ["evaluate_nctb_retrieval.py", str(corpus)]
    try:
        assert module.main() == 0
    finally:
        sys.argv = argv
    return json.loads((corpus / "retrieval_eval.json").read_text(encoding="utf-8"))


def test_ndcg_at_10_is_rank_weighted() -> None:
    module = _load_script()
    assert module.ndcg_at([1]) == 1.0
    assert module.ndcg_at([2]) == round(1 / 1.584962500721156, 4)
    assert module.ndcg_at([11]) == 0.0  # outside the top-k
    assert module.ndcg_at([1, 0]) == 0.5  # a miss contributes nothing


def test_bootstrap_ci_brackets_the_mean_and_is_deterministic() -> None:
    module = _load_script()
    values = [1.0] * 90 + [0.0] * 10
    low, high = module.bootstrap_ci(values, seed=7)
    assert low <= sum(values) / len(values) <= high
    assert module.bootstrap_ci(values, seed=7) == [low, high], "seeded CI must be reproducible"
    assert module.bootstrap_ci([], seed=7) == [0.0, 0.0]


def test_recall_at_1_counts_rank_one_only() -> None:
    module = _load_script()
    assert module._recall_at_1([1, 4]) == 1.0
    assert module._recall_at_1([2]) == 0.0
    assert module._recall_at_1([]) == 0.0


def test_rrf_only_rerank_uses_fusion_and_lexical_base() -> None:
    module = _load_script()
    scores = module.rrf_only_rerank("q", [(None, 0.5, 2.0), (None, 0.25, 1.0)])
    assert scores == [2.5, 1.25]


def test_report_exposes_every_lane_and_extended_metric(synthetic_report: dict) -> None:
    assert set(synthetic_report["variants"]) == {"lexical", "vector", "hybrid-no-rerank", "hybrid"}
    for lane, block in synthetic_report["variants"].items():
        for family in ("A", "B", "D"):
            metrics = block[family]
            for key in (
                "recall_at_1",
                "recall_at_3",
                "recall_at_5",
                "recall_at_10",
                "ndcg_at_10",
                "mrr",
                "recall_at_1_ci95",
                "ndcg_at_10_ci95",
            ):
                assert key in metrics, f"{lane}.{family} missing {key}"
        assert block["latency"]["p50_ms"] >= 0
        assert block["latency"]["p95_ms"] >= 0


def test_report_carries_run_conditions_and_footprint(synthetic_report: dict) -> None:
    conditions = synthetic_report["run_conditions"]
    assert conditions["top_k_evaluated"] == 10
    assert conditions["bootstrap_resamples"] >= 100
    assert conditions["queries_family_a"] > 0
    assert synthetic_report["index_footprint"]["build_peak_memory_mb"] > 0
    # the loader's dedupe invariant: no (class_level, text) pair is served twice
    assert synthetic_report["serve_stats"]["served_duplicate_class_text_pairs"] == 0
    # the class-range fallback serves the same text under several labels; that
    # is what the informational counter is for
    assert synthetic_report["serve_stats"]["served_duplicate_text_groups"] > 0


def test_report_carries_gate_calibration(synthetic_report: dict) -> None:
    calibration = synthetic_report["gate_threshold_calibration"]
    assert calibration["min_coverage_default"] == 0.5
    assert "0.5" in calibration["thresholds"]
    # the calibration must be a measurement, not a copy of the default
    assert "answerable_pass_rate" in calibration["thresholds"]["0.5"]
    assert calibration["adversarial_mean_coverage"] <= calibration["answerable_mean_coverage"] + 0.5


def test_report_carries_the_lexicon_audit(synthetic_report: dict) -> None:
    audit = synthetic_report["lexicon_audit"]
    assert audit["stem_groups"] > 0
    assert audit["collision_ratio"] <= 1.0
    assert isinstance(audit["expansion_targets_absent_from_corpus"], list)


def test_recall_is_monotone_in_k(synthetic_report: dict) -> None:
    for block in synthetic_report["variants"].values():
        for family in ("A", "B", "D"):
            metrics = block[family]
            assert metrics["recall_at_1"] <= metrics["recall_at_3"] <= metrics["recall_at_5"]
            assert metrics["recall_at_5"] <= metrics["recall_at_10"]


def test_banglish_family_is_measured_not_assumed(synthetic_report: dict) -> None:
    assert synthetic_report["family_D_banglish"]["n"] > 0
