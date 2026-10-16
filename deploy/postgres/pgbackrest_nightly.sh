#!/bin/bash
# S5.7 -- pgBackRest nightly full backup loop (backup sidecar entrypoint).
# WAL archiving (archive_command in the postgres service) runs continuously,
# so the effective RPO is the WAL segment flush interval, not the nightly
# cycle; the nightly full is the restore baseline. Retention is enforced by
# repo1-retention-full in pgbackrest.conf.
#
# Env:
#   BACKUP_INTERVAL_SECONDS  gap between nightly runs (default 86400)
#   PGBR_STANZA              stanza name (default bgpt)
set -euo pipefail
STANZA="${PGBR_STANZA:-bgpt}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

echo "pgbackrest nightly loop: stanza=$STANZA interval=${INTERVAL}s"
while true; do
  if pgbackrest --stanza="$STANZA" --type=full backup; then
    echo "nightly full backup OK $(date -u +%FT%TZ)"
  else
    # Never die on a failed run: log loudly, retry next cycle, let the
    # monitoring alert (pgbackrest_info via node-exporter textfile, or the
    # exit code surfaced in container logs) page an operator.
    echo "ERROR: nightly backup FAILED $(date -u +%FT%TZ)" >&2
  fi
  sleep "$INTERVAL"
done
