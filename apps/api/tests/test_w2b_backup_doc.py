"""F-176/DB-08: the backup/DR runbook states the live SQLite pragma values.

The runbook's WAL warning originally said ``busy_timeout=5000`` while
db/session.py sets ``SQLITE_BUSY_TIMEOUT_MS = 15000`` (raised after the
2026-10-24 contention flakes), so an operator reasoning about write
contention from the document reached the wrong conclusion. These tests pin
every pragma number the runbook quotes to the constant the engine applies,
and fail the moment either side drifts.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import re
from pathlib import Path

from bangla_gpt_api.db.session import SQLITE_BUSY_TIMEOUT_MS

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP_DOC = REPO_ROOT / "docs" / "backup_dr.md"


def test_backup_doc_busy_timeout_matches_the_engine_constant() -> None:
    text = BACKUP_DOC.read_text(encoding="utf-8")
    quoted = {int(value) for value in re.findall(r"busy_timeout=(\d+)", text)}
    assert quoted, "the WAL section must state the busy_timeout it relies on"
    assert quoted == {SQLITE_BUSY_TIMEOUT_MS}, (
        f"backup_dr.md quotes busy_timeout {sorted(quoted)} but "
        f"db/session.py applies {SQLITE_BUSY_TIMEOUT_MS}"
    )


def test_backup_doc_names_the_other_pragmas_the_engine_sets() -> None:
    text = BACKUP_DOC.read_text(encoding="utf-8")
    assert "journal_mode=WAL" in text
    assert "foreign_keys=ON" in text
