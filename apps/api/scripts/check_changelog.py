"""VCS-08: the CHANGELOG must account for every commit in the repository.

CHANGELOG.md is generated from git history, so it cannot invent a release. This
check enforces the other direction: a commit that exists but is missing from
the changelog fails CI, which stops the file drifting the moment anyone lands
work without regenerating it.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHANGELOG = REPO / "CHANGELOG.md"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


if not CHANGELOG.is_file():
    print("::error::CHANGELOG.md is missing")
    sys.exit(1)

text = CHANGELOG.read_text(encoding="utf-8")
listed = {line[2:].strip() for line in text.splitlines() if line.startswith("- ")}

# Every non-merge commit reachable from HEAD must be represented.
subjects = [s for s in git("log", "--no-merges", "--format=%s").splitlines() if s.strip()]
missing = [s for s in subjects if s not in listed]


# The changelog rewrites conventional-commit prefixes into prose
# ("fix(api): x" -> "api: x"), so compare on the rewritten form too.
def rewrite(subject: str) -> str:
    head, sep, rest = subject.partition(":")
    if not sep:
        return subject
    head.split("(", 1)[0].strip().rstrip("!")
    if "(" in head:
        scope = head[head.index("(") + 1 : head.rindex(")")].strip()
        rest = rest.strip()
        return f"{scope}: {rest}" if rest else scope
    return subject


still_missing = [s for s in missing if rewrite(s) not in listed]

if still_missing:
    print(
        f"::error::{len(still_missing)} commit(s) are missing from CHANGELOG.md."
        " Regenerate it with `python apps/api/scripts/gen_changelog.py` and"
        " commit the result."
    )
    for subject in still_missing[:15]:
        print("  - " + subject)
    if len(still_missing) > 15:
        print(f"  ... and {len(still_missing) - 15} more")
    sys.exit(1)

# The version headings must match the tags that actually exist.
tag_versions = set(re.findall(r"^## (v[0-9][^\s]*)", text, re.M))
actual_tags = set(git("tag").split())
if tag_versions - actual_tags:
    print(
        f"::error::CHANGELOG.md lists versions with no matching tag: {sorted(tag_versions - actual_tags)}"
    )
    sys.exit(1)

print(
    f"CHANGELOG.md accounts for all {len(subjects)} commits across"
    f" {len(tag_versions)} released versions."
)
