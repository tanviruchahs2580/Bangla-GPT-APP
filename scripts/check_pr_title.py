#!/usr/bin/env python3
"""PR-title lint (audit finding K-02 / AUD-JK-08).

`scripts/check_commits.py` holds a pull request's *commits* to the repository's
Conventional-Commits rule, but the title a reviewer and the squash-merge commit
actually see was never checked. A PR titled "Fix stuff" merges as "Fix stuff"
on `main`, so title linting is the same rule at the other end of the funnel.

Rules are exactly `check_commits.check_subject`'s -- one implementation, three
entry points (history, message file, PR title), so the three cannot drift. The
title is read from, in order:

    --title "feat(api): ..."          explicit (also usable in a test)
    the GITHUB_EVENT_PATH event JSON  `pull_request.title`, set by every
                                      GitHub Actions run on a pull_request
    --file PATH                       a file whose first non-blank line is it
    stdin                             one line

Usage (CI):

    python scripts/check_pr_title.py --strict-length

Exit codes: 0 = the title passes, 1 = a rule violation, 2 = no title to check
(the caller passed no source, e.g. a push event where there is no PR title --
that is "not applicable", not a failure).

Over-length titles are warnings by default and errors under ``--strict-length``,
mirroring check_commits: history cannot be rewritten, but a title can be edited
before the merge, so CI is expected to pass the strict flag.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent


def _load_commit_rules() -> object:
    """Import check_commits.py by path (it is a script, not a package module)."""
    spec = importlib.util.spec_from_file_location("check_commits", SCRIPTS / "check_commits.py")
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise SystemExit("FAIL: cannot load scripts/check_commits.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def title_from_event(path: Path) -> str | None:
    """`pull_request.title` from a GitHub event payload, or None."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pr = payload.get("pull_request")
    if not isinstance(pr, dict):
        return None
    title = pr.get("title")
    return title if isinstance(title, str) and title.strip() else None


def resolve_title(args: argparse.Namespace) -> str | None:
    if args.title is not None:
        return args.title
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_path and Path(event_path).is_file():
        title = title_from_event(Path(event_path))
        if title is not None:
            return title
    if args.file is not None:
        for raw in Path(args.file).read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.strip():
                return raw.strip()
        return None
    if not sys.stdin.isatty():
        for raw in sys.stdin.read().splitlines():
            if raw.strip():
                return raw.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", default=None, help="lint this title and exit")
    parser.add_argument("--file", default=None, help="read the title from this file")
    parser.add_argument(
        "--strict-length",
        action="store_true",
        help="treat a title longer than the 72-char limit as an error (use in CI)",
    )
    args = parser.parse_args(argv)

    title = resolve_title(args)
    if not title:
        print("no pull-request title in this event; nothing to lint (N/A)")
        return 2

    rules = _load_commit_rules()
    errors, warnings = rules.check_subject(title)  # type: ignore[attr-defined]
    if args.strict_length:
        errors, warnings = errors + warnings, []

    print(f"PR-title lint: {title}")
    for message in errors:
        print(f"  ERROR     {message}")
    for message in warnings:
        print(f"  warning   {message}")
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    if errors:
        print(
            "FAIL: retitle the pull request to 'type(scope): summary' "
            "(CONTRIBUTING.md 'Branches and commits')."
        )
        return 1
    print("OK: the title passes the repository rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
