"""Regression tests for the changelog scripts.

Both defects this covers were found against the real repository:

  * `gen_changelog.py` resolved its output path from a hard-coded absolute path
    on the original author's machine, so following README.md's documented
    command from any other checkout wrote CHANGELOG.md somewhere else.
  * `check_changelog.py` demanded a CHANGELOG entry for bot-authored commits,
    which left every automated dependency pull request permanently red.

The scripts are exercised as real subprocesses in a throwaway repository shaped
like this one, because that is the only way to test `REPO` resolution honestly:
the scripts must find their repository from their own location.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BOT_EMAIL = "49699333+dependabot[bot]@users.noreply.github.com"
HUMAN_EMAIL = "287437042+tanviruchahs2580@users.noreply.github.com"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        # S607: bare "git" is resolved through PATH. The test needs the same
        # git the repository is built with; pinning an absolute path here would
        # make the suite fail on any machine that installs it elsewhere.
        ["git", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


_counter = 0


def _commit(repo: Path, subject: str, email: str, name: str = "Someone") -> None:
    """Create one commit, authored by `email`, that always has something to commit.

    The payload goes in a scratch file rather than CHANGELOG.md on purpose:
    check_changelog.py already exempts any commit that touches CHANGELOG.md (the
    regeneration commit cannot contain its own text), so committing the marker
    there would exempt every sandbox commit and the tests would assert nothing.
    """
    global _counter  # noqa: PLW0603
    import os

    with (repo / "notes.md").open("a", encoding="utf-8") as fh:
        fh.write(f"change {_counter}\n")
    _counter += 1

    env_over = {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
    old = {k: os.environ.get(k) for k in env_over}
    os.environ.update(env_over)
    try:
        # Stage only the scratch file. A regenerated CHANGELOG.md is left
        # uncommitted on purpose: staging it would make the next commit touch
        # CHANGELOG.md and so inherit the regeneration exemption.
        _git(repo, "add", "notes.md")
        _git(repo, "commit", "-m", subject)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A git repo with the scripts installed at the path they expect."""
    repo = tmp_path / "repo"
    scripts = repo / "apps" / "api" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("_changelog_common.py", "gen_changelog.py", "check_changelog.py"):
        shutil.copy(SCRIPTS / name, scripts / name)
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", HUMAN_EMAIL)
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _run(repo: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(repo / "apps" / "api" / "scripts" / script)],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_scripts_resolve_their_own_repository(sandbox: Path) -> None:
    """A hard-coded REPO would write outside sandbox; this asserts it does not."""
    _commit(sandbox, "feat: first thing", HUMAN_EMAIL)

    result = _run(sandbox, "gen_changelog.py")

    assert result.returncode == 0, result.stderr
    generated = sandbox / "CHANGELOG.md"
    assert generated.is_file(), "generator did not write into the repository it lives in"
    assert "feat: first thing" in generated.read_text(encoding="utf-8")


def test_bot_commits_are_exempt_from_changelog_coverage(sandbox: Path) -> None:
    """A dependency bump must not fail the gate; a human commit still must."""
    _commit(sandbox, "feat: human work", HUMAN_EMAIL)
    _run(sandbox, "gen_changelog.py")
    assert _run(sandbox, "check_changelog.py").returncode == 0

    _commit(sandbox, "build(docker): bump node from 24-alpine to 26-alpine in /apps/web", BOT_EMAIL)

    result = _run(sandbox, "check_changelog.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 bot commit(s) exempt" in result.stdout


def test_human_commits_are_still_required(sandbox: Path) -> None:
    """The exemption is scoped to the bot identity, not to the commit subject."""
    _commit(sandbox, "feat: human work", HUMAN_EMAIL)
    _run(sandbox, "gen_changelog.py")
    _commit(sandbox, "fix(api): a human commit that was never recorded", HUMAN_EMAIL)

    result = _run(sandbox, "check_changelog.py")

    assert result.returncode == 1
    assert "fix(api): a human commit that was never recorded" in result.stdout


def test_bot_exemption_does_not_depend_on_the_subject(sandbox: Path) -> None:
    """A bot commit worded like human work is still exempt, and vice versa."""
    _commit(sandbox, "feat: human work", HUMAN_EMAIL)
    _run(sandbox, "gen_changelog.py")

    _commit(sandbox, "feat(api): a change a human made that looks like a bot bump", BOT_EMAIL)
    _commit(sandbox, "build(python): bump redis from 5.3.1 to 8.1.0 in /apps/api", HUMAN_EMAIL)

    result = _run(sandbox, "check_changelog.py")

    assert result.returncode == 1, result.stdout
    # The bot-shaped one is exempt; the human one written in bot shape is not.
    assert "build(python): bump redis" in result.stdout
    assert "feat(api): a change a human made" not in result.stdout


def test_generator_does_not_write_bot_commits_into_the_changelog(sandbox: Path) -> None:
    """Both scripts must agree, or regenerating would re-break the check."""
    _commit(sandbox, "feat: human work", HUMAN_EMAIL)
    _commit(sandbox, "build(ci): bump the actions group with 9 updates", BOT_EMAIL)

    _run(sandbox, "gen_changelog.py")
    text = (sandbox / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "feat: human work" in text
    assert "bump the actions group" not in text
    assert _run(sandbox, "check_changelog.py").returncode == 0


def test_generator_output_is_stable_across_reruns(sandbox: Path) -> None:
    """Regenerating twice must not produce a different file (GIT-10)."""
    _commit(sandbox, "feat: human work", HUMAN_EMAIL)
    _run(sandbox, "gen_changelog.py")
    first = (sandbox / "CHANGELOG.md").read_bytes()

    _run(sandbox, "gen_changelog.py")
    assert (sandbox / "CHANGELOG.md").read_bytes() == first
