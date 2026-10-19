"""A8-10/A10-03: the one-command harness, the version board, the re-index drill.

The A8-10 property is mechanical and therefore testable: the command writes
every artifact into a directory that git ignores, and it re-reads ``git
status`` to state whether the tree changed. These tests pin that property
(the gitignore rule itself, the guard that refuses tracked writes, the
summary's versions block) plus the two A10-03 deliverables -- the version
payload the admin board needs and the side-by-side drill with rollback.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

#: Absolute git path (S607: never depend on PATH resolution in a subprocess).
_GIT = shutil.which("git") or "git"

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    # The argv is fixed and the query is read-only.
    return subprocess.run(  # noqa: S603
        [_GIT, *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60
    )


def test_run_root_is_gitignored_by_construction() -> None:
    """A8-10: the command's output directory cannot dirty the tree."""
    from bangla_gpt_api.evaluation.rag_eval import DEFAULT_RUN_ROOT

    probe = DEFAULT_RUN_ROOT / "probe" / "summary.json"
    completed = _git("check-ignore", "-v", str(probe))
    assert completed.returncode == 0, f"{probe} is NOT gitignored: {completed.stdout}"
    assert "tmp/" in completed.stdout or "tmp\\" in completed.stdout


def test_guard_refuses_a_tracked_artifact_write() -> None:
    """The CLI guard: a casual run cannot rewrite a committed artifact."""
    from bangla_gpt_api.evaluation.cli import _guard_tracked_write

    tracked = API_ROOT / "eval" / "baseline_v2.json"
    assert _guard_tracked_write(tracked, allow=False) is False
    assert _guard_tracked_write(tracked, allow=True) is True
    untracked = API_ROOT / "eval" / "tmp" / "r3-guard-probe.json"
    assert _guard_tracked_write(untracked, allow=False) is True


def test_versions_block_carries_seeds_and_versions() -> None:
    from bangla_gpt_api.evaluation.rag_eval import versions_block

    block = versions_block(API_ROOT)
    assert block["python"].startswith("3.")
    assert block["prompt_version"]
    assert block["golden"]["dataset_hash"] and block["golden"]["test_split_hash"]
    assert set(block["seeds"]) >= {"variant_matrix", "targets_report", "retrieval_eval"}
    assert "fastapi" in block["packages"]


def test_summary_markdown_names_every_artifact() -> None:
    from bangla_gpt_api.evaluation.rag_eval import render_summary_markdown

    summary = {
        "run_id": "20261019T000000Z",
        "elapsed_seconds": 1.0,
        "seed": 1,
        "versions": {
            "python": "3.12.10",
            "platform": "test",
            "packages": {"pytest": "1"},
            "prompt_version": "tutor_system@1",
            "golden": {"dataset_hash": "abc", "test_split_hash": "def", "items": 1},
        },
        "artifacts": ["gate.json"],
        "tracked_tree": {"clean": True, "new_changes": []},
        "gate": {"passed": True, "lines": []},
        "highlights": {"redteam_leaks": 0, "targets_met": ["recall_at_5"], "targets_unmet": []},
    }
    markdown = render_summary_markdown(summary, {"gate.json": {"gate_passed": True}})
    assert "tracked tree clean during the run: **True**" in markdown
    assert "gate.json" in markdown and "3.12.10" in markdown
    assert "recall_at_5" in markdown


def test_version_board_reads_every_identity_from_its_artifact() -> None:
    """A10-03: prompt, index, embedding, thresholds and golden versions."""
    from bangla_gpt_api.evaluation.version_board import version_board

    board = version_board(API_ROOT, index_fingerprint="fp-123", embedding_model="")
    assert board["prompt"]["tutor_system"]
    assert board["prompt"]["judge_prompt_version"]
    assert board["index"]["fingerprint"] == "fp-123"
    assert board["embedding"]["model"] == ""
    assert board["evaluation"]["thresholds_version"] == 1
    assert board["evaluation"]["primary_metric"] == "recall_at_5"
    assert board["evaluation"]["golden"]["test_split_hash"]
    assert board["prompt_registry"]["prompt_count"] > 0


def test_version_board_reports_missing_identity_instead_of_guessing() -> None:
    from bangla_gpt_api.evaluation.version_board import version_board

    board = version_board(API_ROOT)
    assert board["index"]["fingerprint"] is None
    assert "unknown" in board["notes"]


def test_reindex_drill_compares_generations_and_rolls_back() -> None:
    """A10-03: the side-by-side drill, exercised on the real registry."""
    from bangla_gpt_api.evaluation import reindex_drill

    report = reindex_drill.run_drill(golden_path=API_ROOT / "eval" / "golden_v2.json")
    assert set(report["generations"]) == {
        reindex_drill.INCUMBENT,
        *reindex_drill.CANDIDATES,
    }
    assert report["rollback"]["rolled_back_to_incumbent"] is True
    assert report["rollback"]["active_after"] != report["rollback"]["active_before"]
    events = [event for event, _version in report["rollback"]["events"]]
    assert events.count("publish") == 3 and events.count("rollback") == 1
    # The decision rule: a candidate ships only on a strict improvement.
    for name, decision in report["decision"]["candidate_decisions"].items():
        assert decision["ship"] is (decision["delta"] > 0), name
    # Dense-lane evidence exists beside the served metric, so a change that
    # only moves the vector lane is visible.
    for name, block in report["dense_lane"].items():
        assert "recall_at_5" in block, name


def test_drill_holds_the_incumbent_when_the_corpus_cannot_resolve_a_change() -> None:
    """Honest tie handling: equal primary metric keeps the incumbent."""
    from bangla_gpt_api.evaluation import reindex_drill

    report = reindex_drill.run_drill(golden_path=API_ROOT / "eval" / "golden_v2.json")
    incumbent = report["generations"][reindex_drill.INCUMBENT]["recall_at_5"]
    ties = [
        name
        for name, block in report["generations"].items()
        if name != reindex_drill.INCUMBENT and block["recall_at_5"] == incumbent
    ]
    for name in ties:
        assert report["decision"]["candidate_decisions"][name]["ship"] is False


def test_committed_artifacts_quote_the_same_split_as_the_preregistration() -> None:
    """The A8-07/A8-08 artifacts must agree on the frozen split hashes."""
    thresholds = json.loads((API_ROOT / "eval" / "thresholds_v1.json").read_text(encoding="utf-8"))
    for name in ("targets_report.json", "variant_matrix.json"):
        path = API_ROOT / "eval" / name
        if not path.is_file():
            pytest.skip(f"{name} not generated in this checkout")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert (
            payload["run_conditions"]["golden_test_split_hash"]
            == thresholds["split_hashes"]["test"]
        ), name
        assert (
            payload["run_conditions"]["golden_dataset_hash"]
            == thresholds["split_hashes"]["dataset"]
        ), name
