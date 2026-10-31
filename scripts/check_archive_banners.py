"""Archive banner guard (DOC-08 / F-135).

Every Markdown file under ``docs/archive/`` must open with a banner that tells
a reader the file is a point-in-time snapshot. The audit found 49 of 57 files
without one, so an archived claim (an old password-hash description, a
self-assessed score) could be read as current state.

Two banner forms are accepted, because the records that already carried a
banner predate the standard wording:

- the standard block the 2026-10-29 sweep prepended
  (``**Historical, not current.**``), and
- an older ``Archived - superseded`` / ``Historical record, archived``
  statement in the same first lines.

The check is deliberately shallow (first four lines) so a passing file cannot
satisfy it with an incidental mention deep in the body.

    python scripts/check_archive_banners.py   # exit 1 lists the offenders
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1] / "docs" / "archive"
# The directory README *is* the archive's standing statement, but it also
# opens with one of these forms, so no special case is needed.
BANNER = re.compile(r"(historical|archived|superseded)", re.IGNORECASE)
HEAD_LINES = 4


def missing_banner(path: Path) -> bool:
    head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:HEAD_LINES])
    return BANNER.search(head) is None


def main() -> int:
    offenders = sorted(
        p.relative_to(ARCHIVE).as_posix()
        for p in ARCHIVE.rglob("*.md")
        if missing_banner(p)
    )
    checked = sum(1 for _ in ARCHIVE.rglob("*.md"))
    if offenders:
        print(f"FAIL: {len(offenders)} of {checked} archive files lack a banner line:")
        for name in offenders:
            print(f"  {name}")
        return 1
    print(f"OK: all {checked} files under docs/archive/ carry a banner line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
