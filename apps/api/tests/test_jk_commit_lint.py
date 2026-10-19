"""Commit-subject lint rules (audit findings AUD-JK-07 / AUD-JK-08).

The repository documents Conventional Commits with a 72-character subject
limit but nothing enforced it (no commit-msg hook, no CI check). The lint in
`scripts/check_commits.py` is that check; these tests pin its rule set so a
future edit cannot silently loosen it, and run it over real history to prove
the structural rules hold on the current tree.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts/check_commits.py"

_spec = importlib.util.spec_from_file_location("check_commits", SCRIPT)
check_commits = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(check_commits)


def test_conventional_subject_passes() -> None:
    errors, warnings = check_commits.check_subject("fix(api): refuse deletion from impersonation")
    assert errors == []
    assert warnings == []


def test_merge_commits_are_exempt() -> None:
    errors, warnings = check_commits.check_subject("Merge pull request #30 from x/y")
    assert errors == []
    assert warnings == []


def test_non_conventional_subject_is_an_error() -> None:
    errors, _ = check_commits.check_subject("Audit remediation, round 2")
    assert any("Conventional Commits" in message for message in errors)


def test_unknown_type_is_an_error() -> None:
    errors, _ = check_commits.check_subject("fmt: run the formatter")
    assert any("unknown type" in message for message in errors)


def test_junk_subject_is_an_error_even_when_typed() -> None:
    errors, _ = check_commits.check_subject("chore: wip")
    assert errors


def test_over_length_subject_warns_not_errors() -> None:
    errors, warnings = check_commits.check_subject("docs: " + "x" * 80)
    assert errors == []
    assert any("chars (limit 72)" in message for message in warnings)


def test_script_passes_over_recent_history_structure() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--max-count", "30"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no subject-structure errors" in result.stdout


def test_script_strict_length_can_fail() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--max-count", "3", "--strict-length"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 1, result.stdout
