"""PR-title lint (K-02 / AUD-JK-08, R3/WS5).

The repository lints a pull request's *commits* (scripts/check_commits.py, wired
in ci.yml over the PR range) but never the PR title -- and the title is what a
squash merge puts on `main`. `scripts/check_pr_title.py` reuses the same rule
function, so the two cannot drift; these tests pin that reuse and both
severities, and prove the event-payload path CI uses.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "check_pr_title.py"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
    )


def test_conventional_title_passes() -> None:
    res = _run("--title", "feat(api): rotate refresh tokens on use")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "OK" in res.stdout


def test_junk_title_fails() -> None:
    res = _run("--title", "Fix stuff")
    assert res.returncode == 1
    assert "junk subject" in res.stdout
    assert "not Conventional Commits" in res.stdout


def test_over_length_is_a_warning_unless_strict() -> None:
    long_title = "fix(web): " + "correct the label " * 5
    assert len(long_title) > 72
    lenient = _run("--title", long_title)
    assert lenient.returncode == 0, lenient.stdout
    assert "warning" in lenient.stdout
    strict = _run("--title", long_title, "--strict-length")
    assert strict.returncode == 1
    assert "subject is" in strict.stdout


def test_title_is_read_from_a_github_event_payload(tmp_path: Path) -> None:
    """The path CI uses: GITHUB_EVENT_PATH, not a shell-interpolated title."""
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": {"title": "docs(readme): state the Python floor"}}),
        encoding="utf-8",
    )
    env = {"GITHUB_EVENT_PATH": str(event), "PATH": ""}
    res = _run(env=env)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "state the Python floor" in res.stdout

    event.write_text(json.dumps({"pull_request": {"title": "wip"}}), encoding="utf-8")
    res = _run(env=env)
    assert res.returncode == 1, res.stdout


def test_a_push_event_reports_not_applicable(tmp_path: Path) -> None:
    """No pull_request object -> exit 2 ("nothing to lint"), not a failure."""
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"ref": "refs/heads/main", "commits": []}), encoding="utf-8")
    res = _run(env={"GITHUB_EVENT_PATH": str(event), "PATH": ""})
    assert res.returncode == 2
    assert "N/A" in res.stdout


@pytest.mark.parametrize(
    "title",
    [
        "Merge pull request #30 from tanviruchahs2580/audit",  # merge commits are exempt
        "chore(release): 0.9.2",
    ],
)
def test_exempt_and_team_titles_pass(title: str) -> None:
    assert _run("--title", title, "--strict-length").returncode == 0
