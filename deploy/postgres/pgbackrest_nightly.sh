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

# AUD-B-03: the repo is encrypted (repo1-cipher-type=aes-256-cbc), so a
# missing passphrase is a configuration error, not a transient failure.
# Loop-start detection is the difference between "seen immediately in the
# container log" and "one failed backup per day forever"; the passphrase
# itself is never printed.
if [ -z "${PGBACKREST_REPO1_CIPHER_PASS:-}" ]; then
  echo "ERROR: PGBACKREST_REPO1_CIPHER_PASS is empty. The backup repo is encrypted;" >&2
  echo "       set PGBR_CIPHER_PASS (compose) from the host secret store and restart." >&2
  exit 1
fi

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
