"""Every explicitly repo-relative path a document names must exist.

F-040 and the general class of "the README lies" findings: a guide that tells
an operator to run `scripts/pg_backup.py` when the file is `pg_backup.sh` costs
real time during an incident. The deployment guide shipped in this engagement
made exactly that mistake on its first draft, which is why this exists.

## Scope, and why it is narrow

Only a backticked token that **starts with a top-level directory that actually
exists** and contains a slash is treated as a repo-relative path assertion.

That is deliberately conservative, because a broader heuristic was tried first
and produced 463 false hits, almost all of the same two kinds:

  * `nctb/bijoy.py`, `services/govt_report.py`, `LoginPage.tsx` -- these are
    written relative to the package or to `apps/web/src`, which is the normal
    style in this repository and is not a broken reference.
  * `test_password_reset.py` -- a bare test filename used as prose, where the
    real file is `apps/api/tests/test_password_reset.py`.

An earlier session's link checker made the same kind of mistake (counting
backticked prose as references, ~500 false breaks). A check that cries wolf is
worse than no check, because it gets deleted.

Excluded: URLs, anchors, and anything under data/nctb (not shipped).

## Two holes closed on 2026-10-17

* The extension list stopped at `.md`/`.ts`/`.css`/`.example`, so whole classes
  of path were invisible while the CI step is named "Every repo path a document
  names exists". `deploy/DEPLOYMENT.md` pointed at
  `deploy/postgres/Caddyfile.template` -- a file that has never existed -- and
  the guard could not see it, because `.template` was not in the list. The
  classes are now spelled out.
* The scan walked the working tree, so it read files git does not track. In CI
  those are absent and the check passes; on a developer machine they are
  present and it fails on a path inside, say, an editor's scratch directory.
  A guard that is green in CI and red locally teaches people to ignore it, so
  directories whose name starts with a dot are skipped.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # .../clone/apps/api/scripts/... -> root

# As posix: str(PurePath) uses the OS separator, so a docs/archive/ prefix
# silently failed to match on Windows and the archive was scanned anyway.
UNTRACKED_PREFIXES = (
    "data/nctb/",
    "node_modules/",
    "dist/",
    "apps/web/android/",
    # Archived reports describe a PAST state of the tree by definition;
    # holding them to today's file list would be nonsense.
    "docs/archive/",
)

PATH_LIKE = re.compile(
    r"`([A-Za-z0-9_][A-Za-z0-9_./-]*"
    r"(?:\.py|\.sh|\.yml|\.yaml|\.toml|\.json|\.md|\.ts|\.tsx|\.css|\.example"
    r"|\.template|\.js|\.jsx|\.txt|\.conf|\.html|\.sql|\.ini|\.cfg|\.ps1|\.lock))"
    r"`"
)


def top_level_dirs() -> set[str]:
    return {p.name for p in REPO.iterdir() if p.is_dir() and p.name not in {".git"}}


def is_untracked_scan_target(path: Path) -> bool:
    """True for paths git does not track, so CI and a local run agree.

    `.gitignore` keeps dot-directories out of the repository (`.zcode/`,
    `.venv/`, editor state). They exist locally and not in CI, which is exactly
    the asymmetry that makes a check untrustworthy.
    """
    return any(part.startswith(".") for part in path.relative_to(REPO).parts[:-1])


def main() -> int:
    tops = top_level_dirs()
    problems: list[tuple[str, str]] = []
    checked = 0

    docs = sorted(
        p
        for p in REPO.rglob("*.md")
        if not any(p.relative_to(REPO).as_posix().startswith(x) for x in UNTRACKED_PREFIXES)
        and "node_modules" not in p.parts
        and not is_untracked_scan_target(p)
    )
    for doc in docs:
        text = doc.read_text(encoding="utf-8", errors="replace")
        for token in sorted(set(PATH_LIKE.findall(text))):
            if "/" not in token:
                continue  # a bare filename is prose, not a path assertion
            if any(tok in token for tok in ("YYYY", "MM-DD", "<", "{")):
                continue  # a template placeholder, e.g. docs/qa-audit-YYYY-MM-DD.md
            if token.split("/", 1)[0] not in tops:
                continue  # written relative to a package, not the repository
            checked += 1
            if not (REPO / token).exists():
                problems.append((str(doc.relative_to(REPO)), token))

    if not problems:
        print(f"all {checked} repo-relative paths named across {len(docs)} markdown files exist")
        return 0

    for doc, token in sorted(problems):
        print(f"::error file={doc}::{token} does not exist")
    print(f"{len(problems)} documentation path(s) do not exist")
    return 1


if __name__ == "__main__":
    sys.exit(main())
