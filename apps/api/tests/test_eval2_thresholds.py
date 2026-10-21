"""A8-07 / AUD-A2-13: the pre-registration file and its change-management hook.

The point of these tests is that the pre-registration is *pinned to the code*:
the tolerance in the committed file must equal the constant CI enforces, the
primary metric must equal the retrieval metric layer's, and a revision that
moves or lowers a threshold without a changelog entry must be rejected.
"""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

import pytest

from bangla_gpt_api.evaluation import thresholds as th
from bangla_gpt_api.evaluation.metrics import GATE_PP
from bangla_gpt_api.evaluation.retrieval_strata import PRIMARY_METRIC

API_ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = API_ROOT / "eval" / "thresholds_v1.json"


def _load() -> dict:
    return th.load_thresholds(THRESHOLDS)


def test_committed_thresholds_match_the_code_that_enforces_them() -> None:
    payload = _load()
    th.validate_against_code(payload)
    assert payload["gate"]["tolerance_pp"] == GATE_PP
    assert payload["primary_metric"] == PRIMARY_METRIC
    assert payload["version"] == len(payload["changelog"])
    assert payload["changelog"][0]["version"] == 1
    # the split the pre-registration names is the frozen one in the golden file
    golden = json.loads((API_ROOT / "eval" / "golden_v2.json").read_text(encoding="utf-8"))
    assert payload["split_hashes"]["dataset"] == golden["dataset_hash"]
    assert payload["split_hashes"]["test"] == golden["test_split_hash"]
    # every A8-08 target class is recorded with a comparison
    for name in ("recall_at_5", "mrr_at_10", "citation_precision", "abstention_recall"):
        assert payload["targets"][name]["comparison"] in {">=", "<=", "=="}


def test_loader_rejects_a_version_without_its_changelog_entry(tmp_path: Path) -> None:
    payload = _load()
    # One *past* the register's own version: a hard-coded number here becomes a
    # no-op the moment the register reaches it (it did: v3 is a real revision
    # with its entry, so the loader rightly accepted it and this test stopped
    # testing anything).
    payload["version"] = int(payload["version"]) + 1
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(th.ThresholdError, match="changelog entries"):
        th.load_thresholds(path)


def test_loader_rejects_a_target_without_a_comparison(tmp_path: Path) -> None:
    payload = _load()
    payload["targets"]["recall_at_5"] = {"target": 0.85}
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(th.ThresholdError, match="comparison"):
        th.load_thresholds(path)


def test_revision_must_bump_the_version() -> None:
    old = _load()
    new = copy.deepcopy(old)
    with pytest.raises(th.ThresholdError, match="bump version"):
        th.validate_revision(old, new)


def test_revision_must_name_every_moved_threshold() -> None:
    old = _load()
    new = copy.deepcopy(old)
    new["version"] = old["version"] + 1
    new["targets"]["mrr_at_10"] = {"target": 0.75, "comparison": ">="}
    new["changelog"].append(
        {"version": new["version"], "date": "2026-11-01", "change": "", "moved_from": None}
    )
    with pytest.raises(th.ThresholdError, match="moved thresholds"):
        th.validate_revision(old, new)


def test_lowering_a_target_needs_a_written_reason() -> None:
    old = _load()
    new = copy.deepcopy(old)
    new["version"] = old["version"] + 1
    new["targets"]["mrr_at_10"] = {"target": 0.60, "comparison": ">="}
    new["changelog"].append(
        {
            "version": new["version"],
            "date": "2026-11-01",
            "change": "mrr_at_10 target moved 0.70 -> 0.60",
            "moved_from": None,
        }
    )
    with pytest.raises(th.ThresholdError, match="lowered targets"):
        th.validate_revision(old, new)
    # with the reason recorded the same revision is a declared act and passes
    new["changelog"][-1]["moved_from"] = (
        "0.70 -> 0.60: the old target was never measurable on the available corpus "
        "(mrr 0.6107); recorded before the next pre-registered comparison"
    )
    th.validate_revision(old, new)


def test_tolerance_change_is_itself_a_moved_threshold() -> None:
    old = _load()
    new = copy.deepcopy(old)
    new["version"] = old["version"] + 1
    new["gate"]["tolerance_pp"] = 5.0
    new["changelog"].append(
        {"version": new["version"], "date": "2026-11-01", "change": "", "moved_from": None}
    )
    with pytest.raises(th.ThresholdError, match=r"gate\.tolerance_pp"):
        th.validate_revision(old, new)


def test_change_management_lists_the_evidence_each_change_kind_needs() -> None:
    assert th.required_evidence("model") == ("apps/api/eval/generation_report.json",)
    assert "apps/api/eval/strata_report.json" in th.required_evidence("index")
    with pytest.raises(th.ThresholdError, match="unknown change kind"):
        th.required_evidence("no-such-change")


def test_missing_and_stale_evidence_are_reported(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "apps" / "api" / "eval").mkdir(parents=True)
    assert th.missing_evidence("model", repo_root) == ["apps/api/eval/generation_report.json"]
    assert th.missing_evidence("index", repo_root) == [
        "apps/api/eval/strata_report.json",
        "data/nctb/retrieval_eval.json",
    ]
    artifact = repo_root / "apps" / "api" / "eval" / "generation_report.json"
    artifact.write_text("{}", encoding="utf-8")
    assert th.missing_evidence("model", repo_root) == []
    # An artifact older than the changed source is not evidence about it. The
    # mtimes are set explicitly: relying on write ORDER made this test flaky on
    # filesystems whose timestamps are coarse enough for two writes to land in
    # the same tick (measured on Windows: the artifact then read as fresh).
    changed = repo_root / "services.py"
    changed.write_text("# changed after the report was written", encoding="utf-8")
    now = time.time()
    os.utime(artifact, (now - 3600, now - 3600))
    os.utime(changed, (now, now))
    assert th.stale_evidence("model", repo_root, [changed]) == [
        "apps/api/eval/generation_report.json"
    ]
    # ... and an artifact newer than every changed source is not stale.
    os.utime(artifact, (now + 60, now + 60))
    assert th.stale_evidence("model", repo_root, [changed]) == []
    assert th.stale_evidence("model", repo_root, []) == []
