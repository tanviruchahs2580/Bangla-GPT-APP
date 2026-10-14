"""Shared constants for the changelog scripts.

Both `gen_changelog.py` (which writes the file) and `check_changelog.py` (which
verifies it) have to agree on two things: which repository they are operating
on, and which commits are allowed to be absent from CHANGELOG.md. Keeping
either in two places produced a real defect: the generator resolved REPO from
a hard-coded absolute path on the original author's machine, so following
README.md's documented command from any other checkout wrote CHANGELOG.md into
that other checkout, or failed outright on Linux.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# apps/api/scripts/_changelog_common.py -> apps/api -> apps -> repository root
REPO = Path(__file__).resolve().parents[3]

# Commit authors exempt from CHANGELOG coverage. These are GitHub's reserved
# bot identities: a dependency bump proposed by Dependabot carries its own pull
# request description and file-level diff, which is where that change is meant
# to be reviewed and recorded. Requiring a hand-edited changelog entry on top of
# that made every automated dependency pull request permanently red -- seven of
# the last eight failing CI runs were Dependabot pull requests failing exactly
# this check -- while adding no information.
#
# Matched on the noreply address, which GitHub reserves for the bot account and
# a human cannot hold. This is a documentation gate, not a security boundary: a
# maintainer could set user.email locally to a bot address and push. What
# actually protects the content of a dependency pull request is the required
# review on `main`, not this exemption.
BOT_AUTHOR_EMAILS = frozenset(
    {
        "49699333+dependabot[bot]@users.noreply.github.com",
    }
)

# sha, author name, author email, subject -- separated by a unit separator so a
# subject containing spaces or colons cannot break the parse. No trailing
# separator: `parse_commit` splits on a fixed count from the left.
COMMIT_FORMAT = "%H%x1f%an%x1f%ae%x1f%s"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


def is_bot(email: str) -> bool:
    return email.strip().lower() in BOT_AUTHOR_EMAILS


def parse_commit(line: str) -> tuple[str, str, str, str]:
    """Split one COMMIT_FORMAT record into (sha, author, email, subject).

    A subject may itself contain the unit separator, so the first three fields
    are positional and everything after them is the subject.
    """
    sha, author, email, subject = line.split("\x1f", 3)
    return sha, author, email, subject
