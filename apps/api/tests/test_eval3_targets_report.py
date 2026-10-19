"""A8-08: the targets report covers every pre-registered target honestly.

The properties pinned here are the ones that make the report trustworthy: no
target silently disappears, every measured row carries a value *with* its
scope and source, every unmeasurable row says why instead of guessing, and
the derived rows declare the derivation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bangla_gpt_api.evaluation import targets_report

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "golden_v2.json"
REDTEAM = Path(__file__).resolve().parents[1] / "eval" / "redteam_v2.json"
THRESHOLDS = Path(__file__).resolve().parents[1] / "eval" / "thresholds_v1.json"


@pytest.fixture(scope="module")
def report() -> dict:
    import asyncio

    return asyncio.run(
        targets_report.build_targets_report(
            golden_path=GOLDEN, redteam_path=REDTEAM, thresholds_path=THRESHOLDS
        )
    )


def test_every_pre_registered_target_has_a_row(report: dict) -> None:
    """Nothing in thresholds_v1.json may be absent from the report."""
    import json

    targets = json.loads(THRESHOLDS.read_text(encoding="utf-8"))["targets"]
    reported = set(report["targets"]) | set(report["not_measured"])
    missing = sorted(set(targets) - reported)
    assert not missing, f"pre-registered targets not reported: {missing}"


def test_measured_rows_name_value_scope_and_source(report: dict) -> None:
    for name, entry in report["targets"].items():
        assert entry["status"] in {"measured", "proxy"}, name
        assert entry["measured"] is not None, name
        assert entry["scope"], name
        assert entry["source"], name
        assert entry["comparison"] in {">=", "<=", "=="}


def test_meets_flag_follows_the_comparison(report: dict) -> None:
    for name, entry in report["targets"].items():
        value, target = entry["measured"], entry["target"]
        if entry["comparison"] == ">=":
            assert entry["meets"] is (value >= target), name
        elif entry["comparison"] == "<=":
            assert entry["meets"] is (value <= target), name
        else:
            assert entry["meets"] is (value == target), name


def test_met_and_unmet_partition_the_targets(report: dict) -> None:
    assert set(report["met"]) | set(report["unmet"]) == set(report["targets"])
    assert not set(report["met"]) & set(report["unmet"])


def test_unmeasured_targets_carry_a_reason_not_a_number(report: dict) -> None:
    for name, reason in report["not_measured"].items():
        assert isinstance(reason, str) and len(reason) > 20, name
    for key in ("answer_correctness", "answer_relevance"):
        assert "live model" in report["not_measured"][key]


def test_unsupported_claim_rate_is_the_declared_derivation(report: dict) -> None:
    span = report["targets"]["unsupported_claim_rate"]
    faithfulness = report["targets"]["faithfulness"]
    assert span["status"] == "proxy"
    assert span["measured"] == pytest.approx(1 - faithfulness["measured"], abs=1e-4)
    assert "derived" in span["source"] or "derivation" in span["note"]


def test_leak_scan_uses_the_same_markers_as_the_gate(report: dict) -> None:
    from bangla_gpt_api.evaluation.generation import leak_markers
    from bangla_gpt_api.services.tutor import SYSTEM_PROMPT

    assert report["leak_scan"]["markers"] == list(leak_markers(SYSTEM_PROMPT))
    assert report["leak_scan"]["leaks_total"] == len(report["leak_scan"]["leaks"])
    assert report["leak_scan"]["redteam_total"] > 0


def test_no_question_or_answer_text_reaches_the_report(report: dict) -> None:
    """The artifact is committed: it must not carry student-adjacent text.

    Checked concretely -- every golden question text must be absent -- rather
    than by grepping for the word "answer", which legitimate prose uses.
    """
    import json

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    payload = json.dumps(report, ensure_ascii=False)
    leaked = [item["question"] for item in golden["items"] if item["question"] in payload]
    assert not leaked, f"question text reached the report: {leaked[:3]}"
    # No stored response text either: the report says what it measured, not
    # what was generated (the key would carry the raw answer if it leaked).
    assert '"answer"' not in payload
    assert "'answer'" not in payload


def test_citation_precision_ci_is_a_cluster_bootstrap(report: dict) -> None:
    """The interval must be computed over items, not over the point estimate."""
    entry = report["targets"]["citation_precision"]
    low, high = entry["ci95"]
    assert low <= entry["measured"] <= high
    assert high - low < 0.5, "a zero-width CI would mean the bootstrap never ran"


def test_markdown_summary_lists_every_target(report: dict) -> None:
    markdown = targets_report.markdown_summary(report)
    for name in report["targets"]:
        assert name in markdown


def test_a_split_with_no_items_fails_loudly() -> None:
    """A8-08 is about the frozen split; a zero-item slice must not report 0.0.

    Found by running the CLI with the gate's default split (`all`, which has
    no per-split items): faithfulness came out 0.0 -- a number nobody
    measured. The guard makes that a startup error instead.
    """
    import asyncio

    with pytest.raises(SystemExit, match="frozen dev/test split"):
        asyncio.run(
            targets_report.build_targets_report(
                golden_path=GOLDEN, redteam_path=REDTEAM, thresholds_path=THRESHOLDS, split="all"
            )
        )
