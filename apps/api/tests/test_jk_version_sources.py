"""The version is stated in several files; this pins that they agree.

Audit finding AUD-JK-12 (work item J-11): the version was hardcoded in
pyproject.toml, apps/web/package.json, package-lock.json, the config.py
fallback, README.md and the deployment guide, and nothing asserted they agree.
`scripts/check_version.py` names `apps/api/pyproject.toml` as the single source
of truth and fails on any disagreement. These tests run the script as a
subprocess against the real tree (must pass) and against a synthetic drifted
tree (must fail), because the property that matters is the exit status.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts/check_version.py"

FILES = [
    "apps/api/pyproject.toml",
    "apps/api/src/bangla_gpt_api/config.py",
    "apps/web/package.json",
    "apps/web/package-lock.json",
    "README.md",
    "docs/operations/PRODUCTION_DEPLOYMENT.md",
    "CHANGELOG.md",
]


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env={"CHECK_VERSION_ROOT": str(root), "PATH": ""},
    )


def test_real_tree_versions_agree() -> None:
    result = _run(REPO)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: every recorded version matches" in result.stdout


def test_a_drifted_version_is_rejected(tmp_path: Path) -> None:
    for rel in FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, target)
    lock = tmp_path / "apps/web/package-lock.json"
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["version"] = "0.0.1"
    lock.write_text(json.dumps(data), encoding="utf-8")

    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "DRIFT" in result.stdout
    assert "apps/web/package-lock.json" in result.stdout


def test_missing_version_file_is_reported(tmp_path: Path) -> None:
    for rel in FILES:
        if rel == "CHANGELOG.md":
            continue
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, target)
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n", encoding="utf-8")

    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "MISSING" in result.stdout
