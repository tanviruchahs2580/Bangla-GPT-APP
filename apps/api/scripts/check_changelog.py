"""VCS-08: the CHANGELOG must account for every commit in the repository.

CHANGELOG.md is generated from git history, so it cannot invent a release. This
check enforces the other direction: a commit that exists but is missing from
the changelog fails CI, which stops the file drifting the moment anyone lands
work without regenerating it.
"""

import re
import sys

from _changelog_common import COMMIT_FORMAT, REPO, git, is_bot, parse_commit

CHANGELOG = REPO / "CHANGELOG.md"


if not CHANGELOG.is_file():
    print("::error::CHANGELOG.md is missing")
    sys.exit(1)

text = CHANGELOG.read_text(encoding="utf-8")
listed = {line[2:].strip() for line in text.splitlines() if line.startswith("- ")}

# Every non-merge commit reachable from HEAD must be represented.
# A commit that touches CHANGELOG.md itself cannot appear inside the file: the
# content is written before the commit carrying it exists. Exclude those by
# looking at what they changed rather than at their subject, so the rule cannot
# be evaded by wording and cannot hide real work behind a matching prefix.
regen_commits = set(git("log", "--no-merges", "--format=%H", "--", "CHANGELOG.md").split())

commits = []
excluded_bots = 0
for line in git("log", "--no-merges", f"--format={COMMIT_FORMAT}").splitlines():
    sha, _author, email, subject = parse_commit(line)
    if sha in regen_commits or not subject.strip():
        continue
    if is_bot(email):
        # Recorded on the bot's own pull request instead; see _changelog_common.
        excluded_bots += 1
        continue
    commits.append(subject)
subjects = commits

missing = [s for s in subjects if s not in listed]


# The changelog rewrites conventional-commit prefixes into prose
# ("fix(api): x" -> "api: x"), so compare on the rewritten form too.
def rewrite(subject: str) -> str:
    head, sep, rest = subject.partition(":")
    if not sep:
        return subject
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
    + (f" {excluded_bots} bot commit(s) exempt." if excluded_bots else "")
)
