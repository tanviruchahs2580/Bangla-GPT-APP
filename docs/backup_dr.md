# Backup & Disaster Recovery

Goal: **RPO 24h / RTO 4h** for all persistent state. Current design beats
both targets comfortably; the numbers below are measured, not aspirated.

## What there is to back up

| Asset | Where | Protection |
|---|---|---|
| App database (users, quiz attempts, chats, audit_log,...) | Postgres 16 (`pg_data` volume) | pgBackRest WAL archiving + nightly full backups |
| NCTB corpus files | `NCTB_CORPUS_DIR` (rebuilt from source) or S3-compatible bucket | `scripts/s3_corpus_sync.py` keeps an S3 copy; corpus is re-creatable anyway |
| Question-paper PDFs | nowhere -- rendered on demand from DB rows (`services/qp_pdf.py`) | no separate target: a DB restore restores the PDFs |
| Secrets (JWT_SECRET, PII_ENC_KEY, GEMINI_API_KEY, SMTP creds) | host `.env` / secret store | out-of-band; NOT in backups (encrypted data would be useless without keys anyway -- see Key loss below) |

## pgBackRest design

- Image: `deploy/postgres/Dockerfile` -- postgres:16 + the Debian-packaged
  `pgbackrest` binary (installed unpinned; the version is whatever
  `postgres:16`'s apt sources currently ship) + the stanza config baked in
  (no host bind mounts; every config change is a rebuild).
- Continuous WAL archiving: the `postgres` compose service runs with
  `wal_level=replica`, `archive_mode=on`,
  `archive_command=pgbackrest --stanza=bgpt archive-push %p`,
  `archive_timeout=60`.
- Nightly full backups: the `pgbackrest` sidecar (profile `backup`) loops
  `pgbackrest --stanza=bgpt --type=full backup` every
  `BACKUP_INTERVAL_SECONDS` (default 86400).
- Retention: `repo1-retention-full=14` (two weeks of nightlies),
  `repo1-retention-diff=7`, zstd compression.
- Repo lives on the `pgbackrest_repo` volume; for off-site durability point
  `repo1` at S3 (`repo1-type=s3`, `repo1-s3-endpoint`, `repo1-s3-bucket`) or
  rclone-sync the volume -- same stanza, same drills.

Start the stack with backups:
`docker compose --profile postgres --profile backup up -d`

## RPO analysis (data loss tolerance: 24h)

WAL segments are pushed to the archive as they fill or at latest every
`archive_timeout=60` seconds. On a crash the last committed transaction is
recoverable once its segment is archived, so **worst-case RPO is ~1 minute
of transactions -- three orders of magnitude inside the 24h budget.**
Even with the archiver fully broken for a day, the nightly full keeps the
bound at 24h (budget, not plan).

## RTO analysis (outage tolerance: 4h)

Measured restore (2026-09-07, local Docker, full volume wipe + restore +
startup + WAL replay): **9 seconds** wall time. Real-world staging adds:
operator detection/triage (minutes), repo download if off-site (size/
bandwidth -- a nightly full of this DB is tens of MB), DNS/edge re-point.
Documented recovery runbook:

1. Provision new postgres container with the same image + volumes.
2. `pgbackrest --stanza=bgpt --delta restore` (add
   `--type=time --set='<UTC timestamp>'` for point-in-time recovery).
3. Start postgres -- recovery replays archived WAL automatically
   (restore_command is written by pgBackRest).
4. Smoke: `scripts/smoke.sh` against the restored instance.

Budget consumed at last drill: 9s of 14400s.

## Restore drill -- weekly (PASS-WHEN of 5.7)

`scripts/pgbackrest_drill.sh` is the drill: it builds the image, starts a
throwaway cluster with archiving, seeds markers, takes a stanza-create +
check + full backup, writes MORE data after the backup, wipes the data
volume, restores, restarts, and asserts both markers came back (proving WAL
replay, not just dump-and-reload). Exit code 0 = drill pass.

**Last executed: 2026-09-07, local docker, PASS.**
Evidence: drill output `PASS... (9s restore)`; postgres log during recovery:
`restored log file "000000010000000000000005" from archive`, `archive
recovery complete`, new timeline 2 selected.

The weekly cadence on the real staging box is the human/infra step
(a staging server itself is still pending); until then run the drill locally --
it is host-agnostic (needs docker only). Schedule suggestion:
`0 4 * * 1 cd /srv/bangla-gpt && bash scripts/pgbackrest_drill.sh`.

## Key loss caveat (operator duty)

`PII_ENC_KEY` and `JWT_SECRET` are deliberately NOT in backups. Losing
`PII_ENC_KEY` makes `parents.phone_enc` ciphertext unrecoverable: rotate by
re-collecting phone numbers at next guardian login, do NOT delete the key
blindly. Store both in the same secret store with the same backup story.

## SQLite dev fallback

Dev installs on `sqlite:////data/app.db` keep the path:
`scripts/backup_loop.py` (online snapshots, `BACKUP_KEEP_DAYS` pruning,
optional `OFFSITE_SYNC_CMD`) + `scripts/restore_test.py` (monthly restore
rehearsal with `PRAGMA integrity_check`). Postgres + pgBackRest above is the
production path.

**WAL and raw file copies.** Since the engine now runs SQLite in WAL mode
(`db/session.py`: `journal_mode=WAL`, `busy_timeout=5000`,
`foreign_keys=ON`), a committed transaction may live in the `app.db-wal`
sidecar until the next checkpoint. The online-backup script above is
WAL-aware and remains the supported path. An ad-hoc raw copy is only a
complete backup if it takes all three files together (`app.db`,
`app.db-wal`, `app.db-shm`) or first runs `PRAGMA wal_checkpoint(TRUNCATE)`
on a connection to the live database; a bare `cp app.db` can silently lose
the most recent transactions.

## Corpus object storage

`scripts/s3_corpus_sync.py` (optional boto3; any S3-compatible endpoint)
materialises `S3_BUCKET`/`S3_PREFIX` into the local corpus dir before
indexing; refuses keys that would escape the destination. Credentials via
standard `AWS_*` env vars.
