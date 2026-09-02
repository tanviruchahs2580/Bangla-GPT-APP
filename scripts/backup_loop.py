"""Scheduled database backups (B12).

Runs inside the ``backup`` compose sidecar. Supports:
- SQLite: online snapshot via the sqlite3 backup API (safe while the API
  is writing; readers never block).
- PostgreSQL: shells out to ``pg_dump`` (present in postgres-based images;
  when unavailable the loop logs a clear error instead of crashing).

After each successful backup an optional ``OFFSITE_SYNC_CMD`` shell command
is executed (e.g. ``rclone copy /backups remote:bgpt-backups``).
Old backups beyond ``BACKUP_KEEP_DAYS`` are pruned.
"""

import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backup")


def _sqlite_file_from_url(url: str) -> Path:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"not a sqlite URL: {url!r}")
    path = url[len(prefix) :]
    if path.startswith("/"):
        # POSIX absolute path (container default: /data/app.db).
        return Path(path)
    if len(path) >= 2 and path[1] == ":":
        # Windows drive-absolute path (host-side rehearsals).
        return Path(path)
    # Relative path: resolve against the process working directory.
    return Path(path).resolve()


def backup_sqlite(database_url: str, dest_dir: Path) -> Path:
    import sqlite3

    src = _sqlite_file_from_url(database_url)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = dest_dir / f"app-{stamp}.db"
    if not src.exists():
        raise FileNotFoundError(f"database file missing: {src}")
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    integrity = subprocess.run(
        [sys.executable, "-c", f"import sqlite3;c=sqlite3.connect({str(target)!r});print(c.execute('PRAGMA integrity_check').fetchone()[0])"],
        capture_output=True,
        text=True,
        check=True,
    )
    if integrity.stdout.strip() != "ok":
        raise RuntimeError(f"backup failed integrity check: {integrity.stdout!r}")
    logger.info("sqlite backup written: %s", target)
    return target


def backup_postgres(database_url: str, dest_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = dest_dir / f"app-{stamp}.sql.gz"
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        raise FileNotFoundError(
            "pg_dump binary not found in this image; use a dedicated postgres "
            "backup image or mount one that provides postgresql-client"
        )
    with open(target, "wb") as dump_fh:
        subprocess.run([pg_dump, database_url], stdout=dump_fh, check=True)
    logger.info("postgres dump written: %s", target)
    return target


def prune_old(dest_dir: Path, keep_days: int) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=keep_days)
    for candidate in dest_dir.glob("app-*.db"):
        created = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
        if created < cutoff:
            candidate.unlink(missing_ok=True)
            logger.info("pruned old backup: %s", candidate)


def run_once() -> None:
    database_url = os.environ.get("DATABASE_URL", "sqlite:////data/app.db")
    dest_dir = Path(os.environ.get("BACKUP_DIR", "/backups"))
    keep_days = int(os.environ.get("BACKUP_KEEP_DAYS", "14"))
    offsite = os.environ.get("OFFSITE_SYNC_CMD", "").strip()
    dest_dir.mkdir(parents=True, exist_ok=True)

    if database_url.startswith("sqlite"):
        backup_sqlite(database_url, dest_dir)
    elif database_url.startswith(("postgresql", "postgres")):
        backup_postgres(database_url, dest_dir)
    else:
        raise ValueError(f"unsupported DATABASE_URL for backup: {database_url!r}")

    prune_old(dest_dir, keep_days)

    if offsite:
        result = subprocess.run(["sh", "-c", offsite], check=False)
        status = "completed" if result.returncode == 0 else f"failed rc={result.returncode}"
        logger.info("offsite sync %s", status)


def main() -> int:
    interval = int(os.environ.get("BACKUP_INTERVAL_SECONDS", "86400"))
    while True:
        try:
            run_once()
        except Exception:  # keep the loop alive; alerting sees stale backups
            logger.exception("backup failed")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
