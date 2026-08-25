"""Monthly restore rehearsal (B12): prove that the latest backup is usable.

Usage:
    python scripts/restore_test.py [--backup-dir /backups]

Restores the newest ``app-*.db`` snapshot into a temporary file, runs
``PRAGMA integrity_check`` and counts rows in core tables. Exits non-zero
on any failure so it can be wired into cron/CI.
"""

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-dir", default="/backups")
    args = parser.parse_args()

    backups = sorted(Path(args.backup_dir).glob("app-*.db"))
    if not backups:
        print(f"FAIL: no backups found in {args.backup_dir}")
        return 1
    latest = backups[-1]
    print(f"restoring: {latest}")

    with tempfile.TemporaryDirectory() as tmp:
        restored = Path(tmp) / "restored.db"
        shutil.copy2(latest, restored)
        connection = sqlite3.connect(restored)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            print(f"integrity_check: {integrity}")
            if integrity != "ok":
                return 1
            for table in ("users", "students", "quiz_attempts", "password_resets"):
                count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"rows[{table}]: {count}")
        finally:
            connection.close()

    print("PASS: backup restores and queries cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
