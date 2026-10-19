"""Rules of the relative-link checker (audit finding J-04).

`scripts/check_links.py` exists because a documentation tree with broken
internal links sends the reader down a path nobody walked. These tests pin the
parts that are easy to get subtly wrong - what counts as a link, how anchors
are slugified, and what is deliberately *not* checked - plus one run over the
real repository, which is the gate that actually keeps the docs honest.

The end-to-end run is intentionally part of the suite: a link checker that is
never executed on the tree it guards is decoration.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "check_links.py"

_spec = importlib.util.spec_from_file_location("check_links", SCRIPT)
check_links = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(check_links)


def test_missing_relative_target_is_reported(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("see [b](b.md) and [gone](nope.md)\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "a.md")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "missing target: nope.md" in result.stdout
    assert "missing target: b.md" not in result.stdout


def test_existing_relative_target_passes(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("see [b](./b.md)\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "a.md")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "relative links checked: 1" in result.stdout


def test_anchor_is_only_checked_when_asked(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("[jump](b.md#the-section)\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# The section\n", encoding="utf-8")
    without = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "a.md")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert without.returncode == 0
    with_anchors = subprocess.run(
        [sys.executable, str(SCRIPT), "--anchors", str(tmp_path / "a.md")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert with_anchors.returncode == 0
    (tmp_path / "b.md").write_text("# Something else\n", encoding="utf-8")
    broken = subprocess.run(
        [sys.executable, str(SCRIPT), "--anchors", str(tmp_path / "a.md")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert broken.returncode == 1
    assert "missing anchor" in broken.stdout


def test_first_link_failure_message_is_about_the_missing_file(tmp_path: Path) -> None:
    """Regression guard for the test above: it must fail on nope.md, not b.md."""
    (tmp_path / "a.md").write_text("[b](b.md)\n[gone](nope.md)\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "a.md")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    broken_lines = [line for line in result.stdout.splitlines() if "missing target" in line]
    assert len(broken_lines) == 1
    assert "nope.md" in broken_lines[0]


def test_fenced_code_and_external_urls_are_not_links(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(
        "```\n[not a link](nowhere.md)\n```\n"
        "inline `[not either](nowhere2.md)` stays code\n"
        "[web](https://example.invalid/x) [mail](mailto:a@b.test)\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "a.md")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "relative links checked: 0" in result.stdout
    assert "external URLs not checked (offline default): 2 unique" in result.stdout


def test_anchor_slug_follows_github_rules() -> None:
    assert check_links.github_slug("Deploying a release (tag push)") == "deploying-a-release-tag-push"
    assert check_links.github_slug("`alembic check` and the schema") == "alembic-check-and-the-schema"
    assert check_links.github_slug("**Bold** heading") == "bold-heading"


def test_duplicate_headings_get_numeric_suffixes(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("# Same\n\n# Same\n", encoding="utf-8")
    assert check_links.markdown_anchors(tmp_path / "b.md") == {"same", "same-1"}


def test_repository_tree_has_no_broken_relative_links() -> None:
    """The gate: every relative link and anchor in the tracked Markdown."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--anchors"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout
    assert "broken:" not in result.stdout


def test_green_run_still_states_what_was_not_checked() -> None:
    """A passing run must not read as "everything verified": external URLs are
    listed as not checked so the reader knows the check's boundary."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    summary = [line for line in result.stdout.splitlines() if line.startswith("relative links checked:")]
    assert len(summary) == 1
    checked = int(summary[0].split(":")[1].split("in")[0].strip())
    assert checked > 0
    assert "external URLs not checked (offline default)" in result.stdout
