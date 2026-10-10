"""Generate CHANGELOG.md from git history.

Nothing here is invented: every entry is derived from the commits that the
corresponding tag actually contains, grouped by the conventional-commit type
already used in this repository. The AUD-0042 finding explicitly forbids
fabricating historical release notes, so the generator refuses to write a
version whose commits it cannot read.
"""

import subprocess
from collections import OrderedDict
from pathlib import Path

REPO = Path(r"C:\Users\DST\projects\Bangla GPT APP")
OUT = REPO / "CHANGELOG.md"

CATEGORIES = OrderedDict(
    [
        ("feat", "Added"),
        ("fix", "Fixed"),
        ("security", "Security"),
        ("perf", "Performance"),
        ("refactor", "Changed"),
        ("build", "Build and dependencies"),
        ("ci", "CI/CD"),
        ("docs", "Documentation"),
        ("test", "Tests"),
        ("chore", "Maintenance"),
        ("style", "Style"),
        ("fmt", "Maintenance"),
        ("deploy", "Deployment"),
    ]
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def classify(subject: str) -> tuple[str, str]:
    """Return (category, verbatim subject).

    The subject is emitted byte-for-byte so that
    scripts/check_changelog.py can verify the file against git with exact
    string matching. Rewriting it into "nicer" prose would make the changelog
    unverifiable, which is worse than a little redundancy under a heading that
    already carries the meaning.
    """
    head = subject.partition(":")[0]
    kind = head.split("(", 1)[0].strip().rstrip("!")
    return CATEGORIES.get(kind, "Other"), subject.strip()


tags = [t for t in git("tag", "--sort=v:refname").split() if t]
sections = []
previous = None
for tag in tags:
    span = f"{previous}..{tag}" if previous else tag
    subjects = git("log", "--format=%s", span).splitlines()
    if not subjects:
        previous = tag
        continue
    grouped: dict[str, list[str]] = {}
    for subject in subjects:
        category, text = classify(subject)
        grouped.setdefault(category, []).append(text)
    sections.append((tag, previous, grouped))
    previous = tag

lines = [
    "# Changelog",
    "",
    "All notable changes to this project are recorded here.",
    "",
    "The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),",
    "and this project adheres to [Semantic Versioning](https://semver.org/).",
    "",
    "> **How this file is produced.** Entries are generated from the git commits",
    "> each tag actually contains, grouped by conventional-commit type. They are",
    "> a record of what changed, not a claim about user impact - when that",
    "> matters it belongs in the release notes on the GitHub Release, which the",
    "> release workflow generates from these same commits.",
    "",
    "## Unreleased",
    "",
]

# Commits after the newest tag are genuinely unreleased and must be listed,
# not summarised as "nothing yet".
unreleased = []
if tags:
    unreleased = git("log", "--format=%s", f"{tags[-1]}..HEAD").splitlines()
else:
    unreleased = git("log", "--format=%s").splitlines()

if unreleased:
    grouped_unreleased: dict[str, list[str]] = {}
    for subject in unreleased:
        category, text = classify(subject)
        grouped_unreleased.setdefault(category, []).append(text)
    for category in dict.fromkeys([*CATEGORIES.values(), "Other"]):
        items = grouped_unreleased.get(category)
        if not items:
            continue
        lines.append(f"### {category}")
        lines.append("")
        for item in sorted(set(items)):
            lines.append(f"- {item}")
        lines.append("")
else:
    lines.append("Nothing yet.")
    lines.append("")

for tag, previous, grouped in reversed(sections):
    date = git("log", "-1", "--format=%cs", tag).strip()
    lines.append(f"## {tag} - {date}")
    lines.append("")
    # dict.fromkeys: several commit types share one heading (chore/fmt -> Maintenance)
    for category in dict.fromkeys([*CATEGORIES.values(), "Other"]):
        items = grouped.get(category)
        if not items:
            continue
        lines.append(f"### {category}")
        lines.append("")
        for item in sorted(set(items)):
            lines.append(f"- {item}")
        lines.append("")
    if previous:
        lines.append("")
    previous = None

OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="")
print("wrote", OUT, len(lines), "lines;", len(sections), "versions")
