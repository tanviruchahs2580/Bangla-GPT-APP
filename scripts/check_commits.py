"""Commit-subject lint (audit findings AUD-JK-07 / AUD-JK-08, work items K-01/K-02).

Repository rule (CONTRIBUTING.md "Branches and commits", Git SOP §11.3):
Conventional Commits 1.0.0 subject — ``type(scope): imperative summary`` — with
a subject of at most 72 characters, no "wip"/"update"/"fix stuff"/"final"
subjects, and merge commits exempt.

Two severities, on purpose:

* **errors** — the subject does not parse as Conventional Commits, or is a
  junk-only subject ("wip", "update", "fix stuff", "final", "misc"). These
  fail the run (exit 1).
* **warnings** — the subject parses but is longer than 72 characters. History
  cannot be rewritten (audit authorisation: no history rewrite), and 14 of the
  last 50 commits exceed the limit, so length is reported but does not fail
  unless ``--strict-length`` is passed. Wire CI with ``--strict-length`` over
  the pull request's own range so new commits are held to the rule; the
  CONTRIBUTING text now says which part is enforced where.

Usage:

    python scripts/check_commits.py                       # last 50 commits
    python scripts/check_commits.py --max-count 20
    python scripts/check_commits.py --range origin/main..HEAD --strict-length
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)
JUNK_SUBJECTS = {"wip", "update", "updates", "fix stuff", "misc", "final", "tmp", "temp"}

SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z]+)"
    r"(?:\((?P<scope>[^()\s][^()]*)\))?"
    r"(?P<breaking>!)?: (?P<description>\S.*)$"
)

MAX_LENGTH = 72
MERGE_RE = re.compile(r"^(Merge |Merged |Revert \"|\d+\.\d+)")


def check_subject(subject: str) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one subject line."""
    subject = subject.strip()
    errors: list[str] = []
    warnings: list[str] = []

    if MERGE_RE.match(subject):
        return [], []
    if len(subject) > MAX_LENGTH:
        warnings.append(f"subject is {len(subject)} chars (limit {MAX_LENGTH})")

    match = SUBJECT_RE.match(subject)
    if not match:
        errors.append("not Conventional Commits: expected 'type(scope): summary'")
        if subject.lower() in JUNK_SUBJECTS:
            errors.append(f"junk subject {subject!r} is forbidden by CONTRIBUTING.md")
        return errors, warnings

    if match.group("type") not in TYPES:
        errors.append(
            f"unknown type {match.group('type')!r} (allowed: {', '.join(TYPES)})"
        )
    description = match.group("description")
    if description.lower() in JUNK_SUBJECTS:
        errors.append(f"junk description {description!r} is forbidden by CONTRIBUTING.md")
    if description.endswith("."):
        errors.append("description must not end with a period")
    return errors, warnings


def git_subjects(count: int, rev_range: str | None) -> list[tuple[str, str]]:
    if rev_range:
        rev_args = [rev_range]
        format_str = "%h%x00%s"
    else:
        rev_args = [f"-{count}"]
        format_str = "%h%x00%s"
    out = subprocess.run(
        ["git", "log", "--no-merges", f"--format={format_str}", *rev_args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if "\x00" not in line:
            continue
        sha, subject = line.split("\x00", 1)
        rows.append((sha, subject))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-count", type=int, default=50, help="how many commits to scan")
    parser.add_argument(
        "--range",
        default=None,
        help="git revision range (e.g. origin/main..HEAD); overrides --max-count",
    )
    parser.add_argument(
        "--strict-length",
        action="store_true",
        help="treat over-length subjects as errors (use for new commits in CI)",
    )
    args = parser.parse_args(argv)

    subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    rows = git_subjects(args.max_count, args.range)
    scope = args.range or f"last {args.max_count} commits"
    print(f"commit-subject lint over {scope} ({len(rows)} non-merge commits)")

    errors = 0
    warnings = 0
    for sha, subject in rows:
        errs, warns = check_subject(subject)
        if args.strict_length:
            errs, warns = errs + warns, []
        for message in errs:
            errors += 1
            print(f"  ERROR   {sha}  {subject}\n            {message}")
        for message in warns:
            warnings += 1
            print(f"  warning {sha}  {subject}\n            {message}")

    print(f"\n{errors} error(s), {warnings} warning(s)")
    if errors:
        print(
            "FAIL: fix the subject before pushing (CONTRIBUTING.md 'Branches and commits').\n"
            "Historical commits cannot be rewritten; --strict-length applies to new work."
        )
        return 1
    print("OK: no subject-structure errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
