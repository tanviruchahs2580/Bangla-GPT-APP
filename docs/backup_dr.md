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

### Encryption at rest (AUD-B-03)

- `deploy/postgres/pgbackrest.conf` sets `repo1-cipher-type=aes-256-cbc`.
  The pgBackRest binary shipped in the image (2.59.1) accepts exactly
  `none` and `aes-256-cbc`; `aes-256-ctr` is rejected with
  `'aes-256-ctr' is not allowed for 'repo1-cipher-type' option`.
- The passphrase is deliberately not in this repository or in the conf.
  Both the `postgres` service (WAL `archive-push`) and the `pgbackrest`
  sidecar read it from `PGBACKREST_REPO1_CIPHER_PASS`, which compose injects
  from `PGBR_CIPHER_PASS` (a value in the operator's untracked `.env` /
  secret store).
- A missing passphrase fails loudly, never silently plaintext: pgBackRest
  reports `info command requires option: repo1-cipher-pass` (or
  `environment variable 'repo1-cipher-pass' must have a value` when the
  variable is set but empty), and `deploy/postgres/pgbackrest_nightly.sh`
  refuses to start its loop without it.
- Consequence to accept deliberately: the backups are only as recoverable as
  that passphrase. Keep it in the same secret store as `JWT_SECRET` and
  `PII_ENC_KEY`, and keep a copy of the *store* (not the passphrase beside
  the repo -- that would defeat the control).
- Not done in this round (owner action): rotating the passphrase for an
  existing repo. pgBackRest re-encrypts on the next full backup taken with
  the new passphrase; until that full exists, keep the old passphrase
  available for restore.

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

**Status as of the 2026-10-18 hardening round: NOT re-executed.** The
paragraph above is the maintainers' record from 2026-09-07. The remediation
run that enabled backup encryption did not re-run the drill (docker-in-docker
sizing), so the 9 s restore figure stays a claim, not a measurement, and the
next drill must also cover the encrypted repo: export
`PGBACKREST_REPO1_CIPHER_PASS` before running `scripts/pgbackrest_drill.sh`
(the script itself still needs that pass wired into its two docker invocations;
the exact patch is in `.audit/handoffs/ef-from-b.md`).

The weekly cadence on the real staging box is the human/infra step
(staging server itself is pending 🖐); until then run the drill locally --
it is host-agnostic (needs docker only). Schedule suggestion:
`0 4 * * 1 cd /srv/bangla-gpt && bash scripts/pgbackrest_drill.sh`.

## Key loss caveat (operator duty)

`PII_ENC_KEY` and `JWT_SECRET` are deliberately NOT in backups. Losing
`PII_ENC_KEY` makes `parents.phone_enc` ciphertext unrecoverable: rotate by
re-collecting phone numbers at next guardian login, do NOT delete the key
blindly. Store both in the same secret store with the same backup story.

The backup repo passphrase (`PGBR_CIPHER_PASS`) has the same property, one
level up: losing it makes every pgBackRest backup unreadable even though the
backup files themselves are intact (AUD-B-03). Back the secret store up
separately from the database.

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

## Single points of failure (AUD-HI-19)

The design above answers "how do we restore"; this table answers "what, if it
dies right now, takes the product down until a human acts". Each row says
whether the shipped configuration already survives its failure and what the
owner would have to approve to remove the point of failure. Multi-zone and
multi-region topology is an **owner decision** (I10) with a cost estimate --
not something this repository can decide on its own.

| # | Single point of failure | Shipped configuration | Survives its failure? | Removing it requires (owner) |
|---|---|---|---|---|
| 1 | PostgreSQL instance (single volume, single host in the compose profile) | One container + one named volume (`deploy/postgres`) | No -- restore from pgBackRest (RTO budget 4h, last drill 9s) | Managed Postgres with a standby and automatic failover, or a second PG container with streaming replication (ADR + cost) |
| 2 | Redis (rate-limit counters and shared caches) | One container; the API degrades per `RATE_LIMIT_FAIL_OPEN` | Partially -- with `FAIL_OPEN=false` (default) protected routes answer 503; with `true`, limits weaken to per-process | Managed Redis with a replica, or accept a documented availability-over-strictness posture |
| 3 | API host / container (all workers on one machine) | `docker compose` on one host; no second replica | No | Two API replicas behind the proxy (the app is already replica-safe: shared limiter store, SSE, no local job queue). Needs the deploy runbook to describe rolling restarts |
| 4 | Off-site backup copy | **Not configured by default**: `pgbackrest` archives to a local repo unless the operator points it at object storage | No -- host loss loses the backups | Configure the S3/GCS repo (`docs/backup_dr.md` §pgBackRest design) with owner credentials; also test the cross-region throughput |
| 5 | Encryption key for backups | Operator-held; loss is unrecoverable (`docs/backup_dr.md` §Key loss caveat) | n/a | A documented key custodian and an escrow decision (owner) |
| 6 | TLS termination / reverse proxy (Caddy in the documented topology) | One proxy container | No | Terminate TLS at a managed load balancer, or a second proxy with a shared certificate store |
| 7 | LLM provider (single configured provider; fallback optional) | `LLM_PROVIDER` + optional `LLM_FALLBACK_PROVIDER` | Partially -- with a fallback configured, generation continues; without one, students get refusals (never fabrications) | Configure the fallback provider + key, and pay for both |
| 8 | DNS / domain and the outbound SMTP account | Owner-held accounts | No | Provider accounts with recovery contacts recorded in the owner's runbook (not in this repository) |
| 9 | The single deploy credential (SSH key / registry token) | Owner-held | No | A second operator with credentials and a rotation procedure (`docs/runbook.md` §6, §10) |
| 10 | Availability of the application index at boot | Rebuilt in-memory per worker at boot; a bad `NCTB_CORPUS_DIR` silently falls back to the bundled sample | Partially -- `/ready` reports degraded and `HighRAGRefusalRate` fires | A persisted, versioned index (the deferred pgvector/persistence work) |

**Owner decisions requested (I10):** whether to fund rows 1, 2, 3, 4 and 6
(multi-zone posture), and who holds the keys in rows 4, 5 and 9. Until those
are decided, the honest statement of the DR posture is: *single-host with a
tested local restore path*. The audit's RPO/RTO figures above assume that host
still exists to restore onto.

### Restore drill re-run (owner action)

The last recorded destructive `pgbackrest` drill is dated 2026-09-07 (in-repo
claim). This audit could not reproduce it inside its budget: it builds the
pgBackRest image, wipes a volume and restores, and needs an isolated Docker
host. Re-run on staging with:

```bash
cd apps/api && bash scripts/pgbackrest_drill.sh   # see docs/backup_dr.md §Restore drill
```

and record the wall-clock time here. Until that re-run, treat the restore path
as *documented and previously measured*, not *re-verified*.
