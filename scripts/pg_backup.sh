#!/bin/bash
# pg_backup.sh — Postgres backup + restore drill for S0.4
# Usage: DATABASE_URL=postgresql+psycopg://user:pass@host/db ./scripts/pg_backup.sh
# Or: ./scripts/pg_backup.sh backup|restore <file>
set -euo pipefail
DB_URL="${DATABASE_URL:-postgresql+psycopg://bgpt:bgpt@localhost:5432/bgpt}"
# Strip driver prefix for pg_dump (psycopg)
PG_URL=$(echo "$DB_URL" | sed 's|postgresql+psycopg://|postgresql://|')
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/pg_backup_$TIMESTAMP.sql"

if [ "${1:-backup}" = "backup" ]; then
  echo "→ Backing up Postgres to $FILE"
  pg_dump "$PG_URL" > "$FILE"
  echo "✓ Backup written: $FILE ($(wc -c < "$FILE") bytes)"
  ls -lh "$FILE"
elif [ "${1:-}" = "restore" ]; then
  RESTORE_FILE="${2:-}"
  if [ -z "$RESTORE_FILE" ]; then echo "Usage: $0 restore <file>"; exit 1; fi
  echo "→ Restoring Postgres from $RESTORE_FILE"
  psql "$PG_URL" < "$RESTORE_FILE"
  echo "✓ Restore complete"
else
  echo "Usage: $0 [backup|restore <file>]"
  exit 1
fi
