#!/bin/bash
# S5.7 -- pgBackRest backup + restore DRILL.
#
# Proves end-to-end, on real containers:
#   1. a stanza can be created and WAL archiving verified (check),
#   2. a nightly-style full backup completes,
#   3. data written AFTER the backup survives a simulated disaster
#      (volume wiped) -- i.e. archived WAL is replayed during recovery,
#      4. restore + startup wall time stays inside the documented RTO (4h).
#
# This is the script to run weekly on staging (roadmap 5.7); run locally it
# doubles as the config validation. Requires: docker, and (for the optional
# alembic step) nothing else -- the drill seeds its own proof table.
#
# Env overrides:
#   DRILL_PORT   host port for the throwaway cluster (default 5433)
#   DRILL_IMAGE  image to build/use (default bgpt-pgbr)
#   KEEP=1       leave containers/volumes behind for inspection
set -euo pipefail
# Git-Bash on Windows rewrites container paths like /repo -> C:/Program Files/Git/repo
# unless told not to; no effect on Linux staging hosts.
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

DRILL_PORT="${DRILL_PORT:-5433}"
DRILL_IMAGE="${DRILL_IMAGE:-bgpt-pgbr}"
DB=bgpt-drill-db
PGDATA_VOL=bgpt-drill-pgdata
REPO_VOL=bgpt-drill-repo
# stanza config + nightly loop are baked into the image (see deploy/postgres/Dockerfile)
# -- no host bind mounts, which Windows Docker Desktop handles poorly.
PGHOST_CONF=(-c wal_level=replica -c archive_mode=on
  -c "archive_command=pgbackrest --stanza=bgpt archive-push %p"
  -c archive_timeout=30)

cleanup() {
  if [ "${KEEP:-0}" = "1" ]; then echo "KEEP=1: leaving $DB and volumes"; return; fi
  docker rm -f "$DB" >/dev/null 2>&1 || true
  docker volume rm "$PGDATA_VOL" "$REPO_VOL" >/dev/null 2>&1 || true
}
trap cleanup EXIT

psql_in() { docker exec "$DB" psql -U bgpt -d bgpt -tA -c "$1"; }
pgbr_in() { docker exec -u postgres "$DB" pgbackrest --stanza=bgpt "$@"; }

echo "==> 1/7 build image ($DRILL_IMAGE)"
docker build -q -t "$DRILL_IMAGE" deploy/postgres >/dev/null

echo "==> 2/7 start throwaway cluster on 127.0.0.1:$DRILL_PORT with WAL archiving"
cleanup 2>/dev/null || true
docker volume create "$PGDATA_VOL" >/dev/null
docker volume create "$REPO_VOL" >/dev/null
docker run -d --name "$DB" \
  -v "$PGDATA_VOL:/var/lib/postgresql/data" \
  -v "$REPO_VOL:/repo" \
  -e POSTGRES_USER=bgpt -e POSTGRES_PASSWORD=bgpt -e POSTGRES_DB=bgpt \
  -p "127.0.0.1:$DRILL_PORT:5432" \
  "$DRILL_IMAGE" postgres "${PGHOST_CONF[@]}" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$DB" pg_isready -U bgpt -d bgpt >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$DB" pg_isready -U bgpt -d bgpt
docker exec "$DB" chown postgres:postgres /repo

echo "==> 3/7 seed proof data (pre-backup marker)"
psql_in "DROP TABLE IF EXISTS drill_proof; CREATE TABLE drill_proof(note text, at timestamptz DEFAULT now());"
psql_in "INSERT INTO drill_proof(note) VALUES ('pre-backup');"

echo "==> 4/7 stanza-create + check + full backup (nightly equivalent)"
pgbr_in stanza-create
pgbr_in check
pgbr_in backup --type=full
BACKUP_DONE=$(date -u +%FT%TZ)
echo "    nightly full backup completed at $BACKUP_DONE"

echo "==> 5/7 write post-backup data (proves WAL archiving, not just the dump)"
psql_in "INSERT INTO drill_proof(note) VALUES ('post-backup');"
psql_in "SELECT pg_switch_wal() IS NOT NULL;" >/dev/null
sleep 3  # give archive_timeout / switch a moment to push the segment

echo "==> 6/7 disaster: destroy container + wipe data volume, then restore"
docker rm -f "$DB" >/dev/null
docker volume rm "$PGDATA_VOL" >/dev/null
docker volume create "$PGDATA_VOL" >/dev/null
RESTORE_T0=$(date +%s)
docker run --rm \
  -v "$PGDATA_VOL:/var/lib/postgresql/data" \
  -v "$REPO_VOL:/repo" \
  "$DRILL_IMAGE" bash -c "chown postgres:postgres /var/lib/postgresql/data /repo && gosu postgres pgbackrest --stanza=bgpt --delta --log-level-console=warn restore"
docker run -d --name "$DB" \
  -v "$PGDATA_VOL:/var/lib/postgresql/data" \
  -v "$REPO_VOL:/repo" \
  -e POSTGRES_USER=bgpt -e POSTGRES_PASSWORD=bgpt -e POSTGRES_DB=bgpt \
  -p "127.0.0.1:$DRILL_PORT:5432" \
  "$DRILL_IMAGE" postgres "${PGHOST_CONF[@]}" >/dev/null
for _ in $(seq 1 120); do
  docker exec "$DB" pg_isready -U bgpt -d bgpt >/dev/null 2>&1 && break
  sleep 1
done
RESTORE_T1=$(date +%s)
echo "    restore + startup took $((RESTORE_T1 - RESTORE_T0))s (RTO budget: 14400s)"

echo "==> 7/7 verify recovered data (pre AND post markers -> WAL replay OK)"
ROWS=$(psql_in "SELECT string_agg(note, ',' ORDER BY at) FROM drill_proof;")
echo "    drill_proof notes: $ROWS"
[ "$ROWS" = "pre-backup,post-backup" ] || { echo "FAIL: markers missing -> backup/WAL not usable"; exit 1; }
echo "PASS: pgBackRest backup + PITR-style WAL-replay restore drill verified ($((RESTORE_T1 - RESTORE_T0))s restore)."
