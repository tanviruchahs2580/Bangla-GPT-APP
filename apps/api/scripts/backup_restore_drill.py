"""SQLite backup + restore rehearsal with row-count and integrity verification (H-09).

The DR document claims an RPO/RTO and describes the SQLite path
(``scripts/backup_loop.py`` daily snapshots, ``scripts/restore_test.py`` monthly
rehearsal), but the audit's own run could not point at a *rehearsal log* for
this round. This script is that rehearsal, runnable on demand and in CI:

1. open the source database and check it (``integrity_check``,
   ``foreign_key_check``), recording per-table row counts;
2. commit one extra row *after* the last checkpoint, so the newest transaction
   lives only in the ``-wal`` sidecar;
3. take an **online backup** with SQLite's own backup API (WAL-aware, consistent
   under concurrent writers) -- the supported path;
4. restore: materialise the backup as a fresh database file and verify it
   (same checks, same row counts, plus the post-checkpoint row);
5. demonstrate the trap the DR doc warns about: a bare file copy of just
   ``app.db`` misses that row, which is why the raw-copy path is not supported;
6. print a JSON report and exit non-zero if any check fails.

The PostgreSQL/pgBackRest drill is deliberately NOT re-implemented here: it
needs an isolated Docker host and a wipe-and-restore cycle, and it stays an
owner-run step with the exact commands in ``docs/backup_dr.md``.

Usage::

    cd apps/api
    python scripts/backup_restore_drill.py                       # seeded demo database
    python scripts/backup_restore_drill.py --source ./demo.db    # any sqlite database
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
#: The row committed after the last checkpoint; a WAL-unaware copy loses it.
MARKER_EMAIL = "drill-marker@demo.bangla-gpt.test"
MARKER_SQL = (
    "INSERT INTO users (email, password_hash, role, email_verified, must_change_password,"
    " failed_login_count, created_at) VALUES (?, 'x', 'student', 1, 0, 0,"
    " '2026-10-01 00:00:00')"
)


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            " ORDER BY name"
        ).fetchall()
    ]
    return {
        table: int(
            # The identifier comes from sqlite_master in this same database,
            # never from user input, and an identifier cannot be a bind param.
            conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]  # noqa: S608
        )
        for table in tables
    }


def _integrity(conn: sqlite3.Connection) -> dict[str, object]:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    return {
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
        "ok": integrity == "ok" and not foreign_keys,
    }


def _online_backup(source: Path, destination: Path) -> float:
    """SQLite online backup API: consistent even while writers are active."""
    started = time.perf_counter()
    src = sqlite3.connect(source)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return time.perf_counter() - started


def _seed_demo_if_requested(database_url_path: Path) -> Path:
    """Build a small deterministic demo database for the drill."""
    sys.path.insert(0, str(SCRIPTS))
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))
    import seed_demo

    seed_demo.main(
        [
            "--database-url",
            f"sqlite:///{database_url_path.as_posix()}",
            "--env",
            "test",
            "--students",
            "12",
            "--days",
            "5",
        ]
    )
    return database_url_path


def run(source: Path) -> dict[str, object]:
    report: dict[str, object] = {"source": str(source), "checks": {}, "failures": []}
    checks: dict[str, object] = report["checks"]  # type: ignore[assignment]
    failures: list[str] = report["failures"]  # type: ignore[assignment]

    if not source.exists():
        failures.append(f"source database {source} does not exist")
        return report

    with tempfile.TemporaryDirectory(prefix="bgpt-drill-", ignore_cleanup_errors=True) as workdir:
        backup = Path(workdir) / "backup.db"
        restored = Path(workdir) / "restored.db"
        naive_copy = Path(workdir) / "naive-copy.db"

        conn = sqlite3.connect(source)
        try:
            checks["source_before"] = _integrity(conn)
            if not checks["source_before"]["ok"]:  # type: ignore[index]
                failures.append("source database failed integrity_check before the drill")
                return report
            counts_before = _table_counts(conn)
            checks["source_tables"] = len(counts_before)
            # Flush everything to the main file first, so the demonstration
            # isolates ONE variable: a committed write that exists only in the
            # -wal when the copy is taken. (Without this checkpoint the bare
            # copy could be missing the schema itself, which is an even louder
            # failure but muddies the comparison.)
            checks["wal_checkpoint"] = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            # A committed write after the last checkpoint: the classic
            # "backup looks fine, latest data is gone" case.
            conn.execute("DELETE FROM users WHERE email = ?", (MARKER_EMAIL,))
            conn.execute(MARKER_SQL, (MARKER_EMAIL,))
            conn.commit()
            counts_after = _table_counts(conn)
            checks["source_rows_after_marker"] = sum(counts_after.values())
            checks["marker_visible_in_source"] = (
                conn.execute(
                    "SELECT count(*) FROM users WHERE email = ?", (MARKER_EMAIL,)
                ).fetchone()[0]
                == 1
            )
            # WAL reality check: the marker must be in the sidecar, not the main file.
            wal_path = Path(str(source) + "-wal")
            checks["wal_sidecar_bytes"] = wal_path.stat().st_size if wal_path.exists() else 0

            # 1) supported path: online backup
            checks["online_backup_seconds"] = round(_online_backup(source, backup), 3)
            # 2) restore: the backup materialised as a fresh file
            shutil.copyfile(backup, restored)
            # 3) the trap: a bare copy of the main file only
            shutil.copyfile(source, naive_copy)
        finally:
            conn.close()

        restored_counts = {}
        with sqlite3.connect(restored) as restored_conn:
            checks["restored_integrity"] = _integrity(restored_conn)
            if not checks["restored_integrity"]["ok"]:  # type: ignore[index]
                failures.append("restored database failed integrity_check")
            restored_counts = _table_counts(restored_conn)
            checks["restored_rows"] = sum(restored_counts.values())
            checks["marker_visible_in_restore"] = (
                restored_conn.execute(
                    "SELECT count(*) FROM users WHERE email = ?", (MARKER_EMAIL,)
                ).fetchone()[0]
                == 1
            )

        checks["row_counts_identical"] = restored_counts == counts_after
        if restored_counts != counts_after:
            missing = {
                table: (counts_after.get(table, 0), restored_counts.get(table, 0))
                for table in set(counts_after) | set(restored_counts)
                if counts_after.get(table, 0) != restored_counts.get(table, 0)
            }
            failures.append(f"row counts differ after restore: {missing}")
        if not checks["marker_visible_in_restore"]:
            failures.append("the newest committed transaction is missing from the restore")

        # The bare copy: expected to MISS the post-checkpoint commit. This is a
        # demonstration, not a failure of the drill -- if a bare copy ever
        # contained the marker, the hazard would be gone and the doc would need
        # updating.
        with sqlite3.connect(naive_copy) as naive_conn:
            try:
                marker_in_copy = (
                    naive_conn.execute(
                        "SELECT count(*) FROM users WHERE email = ?", (MARKER_EMAIL,)
                    ).fetchone()[0]
                    == 1
                )
                checks["bare_copy_has_schema"] = True
            except sqlite3.Error as exc:
                marker_in_copy = False
                checks["bare_copy_has_schema"] = False
                checks["bare_copy_error"] = str(exc)
            checks["marker_visible_in_bare_copy"] = marker_in_copy

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=None, help="sqlite database to drill")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="build a deterministic demo database first (see scripts/seed_demo.py)",
    )
    args = parser.parse_args(argv)

    if args.source is None:
        tmp = Path(tempfile.mkdtemp(prefix="bgpt-drill-src-"))
        args.source = tmp / "drill-demo.db"
        _seed_demo_if_requested(args.source)
    elif args.demo:
        _seed_demo_if_requested(args.source)

    report = run(args.source)
    report["pg_drill"] = (
        "NOT RUN: the pgBackRest wipe-and-restore drill needs an isolated Docker host and "
        "stays an owner step -- exact commands in docs/backup_dr.md (Restore drill re-run)."
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["failures"]:
        print(f"DRILL FAILED: {report['failures']}")
        return 1
    print("DRILL PASSED: online backup + restore verified (integrity, foreign keys, row counts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
