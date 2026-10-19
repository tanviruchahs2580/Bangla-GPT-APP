# Durability and disaster recovery (operations)

> Audience: whoever gets paged, and the owner deciding what to fund.
> Design detail (pgBackRest stanza, encryption, WAL, corpus sync) lives in
> [`docs/backup_dr.md`](../backup_dr.md); this page is the operational
> schedule, the measured evidence and the owner decisions in one place
> (I-09 / AUD-HI-19).

## 1. Targets and what they cover

| Asset | Store | RPO target | RTO target |
|---|---|---|---|
| Application database (users, chats, attempts, audit, jobs) | Postgres 16 volume (production compose) | 24 h | 4 h |
| Local/self-hosted dev database | SQLite file (`sqlite:////data/app.db`) | 24 h | 4 h |
| NCTB corpus | `NCTB_CORPUS_DIR`, re-buildable; optional S3 copy | n/a (re-creatable) | rebuild time |
| Question-paper PDFs | none — rendered on demand from DB rows | follows the DB | follows the DB |
| Secrets (`JWT_SECRET`, `PII_ENC_KEY`, SMTP, provider keys, `PGBR_CIPHER_PASS`) | operator secret store, deliberately **not** in backups | — | see §5 |

RPO/RTO are the same numbers the audit found documented; they are **not yet
ratified** — ratification is an owner action in `docs/operations/SLO.md`.

## 2. Backup schedule and verification schedule

| Cadence | What | Command | Where it runs |
|---|---|---|---|
| continuous | WAL archiving (`archive_timeout=60`) | pgBackRest `archive-push` (in the `postgres` service) | production compose |
| daily | full backup | `pgbackrest --stanza=bgpt --type=full backup` (the `pgbackrest` sidecar loop) | production compose |
| daily (dev/SQLite) | online snapshot + prune | `python scripts/backup_loop.py` (`BACKUP_INTERVAL_SECONDS`, `BACKUP_KEEP_DAYS`) | dev host |
| **weekly** | restore rehearsal on the SQLite path | `python scripts/restore_test.py --backup-dir "$BACKUP_DIR"` | staging/dev, cron `0 5 * * 1` |
| **weekly** | destructive pgBackRest drill (wipe → restore → WAL replay) | `cd apps/api && bash scripts/pgbackrest_drill.sh` | a Docker host; needs `PGBACKREST_REPO1_CIPHER_PASS` exported |
| **monthly** | off-site copy check (object-storage repo or rclone) | `pgbackrest info --stanza=bgpt` + a restore of the newest set to a scratch host | staging |
| **quarterly** | key-custody review (who holds `PGBR_CIPHER_PASS`, `JWT_SECRET`, `PII_ENC_KEY`) | human checklist, logged here | owner |

A backup that has never been restored is not a backup: the weekly rehearsal is
the control, and its result is the dated line in §4.

## 3. Recovery procedure (short form)

1. Provision a replacement Postgres container with the same image and volumes.
2. `pgbackrest --stanza=bgpt --delta restore` (add `--type=time --set='<UTC>'`
   for point-in-time recovery).
3. Start Postgres; recovery replays archived WAL automatically.
4. Verify: `bash scripts/smoke.sh` against the restored instance, then
   `/ready` and one tutor turn.
5. Rotate nothing; the restored data is only as private as the key store
   (§5). If the incident was a suspected breach, follow the runbook's
   `suspected breach` play instead.

SQLite path: stop the writer, restore the newest `app-*.db` snapshot over the
live file (or point `DATABASE_URL` at the snapshot and restart) — the
snapshot is taken with SQLite's online-backup API, so no WAL sidecar is
involved.

## 4. Measured restore evidence (drill log)

| Date | Path | Data | Backup | Restore (wall) | Result |
|---|---|---|---|---|---|
| 2026-10-18 | SQLite file + `scripts/restore_test.py` | 1 user row (rehearsal) | 1.0 s | <1 s (not timed) | `integrity_check: ok`, rc=0 — E-HI-042 |
| **2026-10-19** | SQLite file + `scripts/restore_test.py` | 2000 users + 50 000 analytics rows, 5.1 MiB | **1.67 s** | **1.32 s** (integrity_check `ok`, row counts verified) | rc=0 — E-R2-i2-005 |
| 2026-09-07 (in-repo claim) | pgBackRest full-volume wipe + WAL replay | production-shaped | — | 9 s | PASS — but **not re-executed by this audit** (needs a Docker host); treat as a dated claim until the weekly drill runs |

Budget consumed: 1.32 s of the 4 h RTO on the local path (0.01 %), with the
caveat that "restore the file" is not "restore the system": detection,
triage, provisioning and DNS re-point are the rest of the RTO and are
practised only in the drill.

## 5. Single points of failure

The shipped compose topology is single-host. Full table with "what would
remove it" lives in [`docs/backup_dr.md` §Single points of failure](../backup_dr.md);
the ones that decide the product's fate today:

1. **PostgreSQL** — one container, one volume. Restore is the only recovery.
2. **Redis** — one container; rate-limit counters and shared caches. With
   `RATE_LIMIT_FAIL_OPEN=false` (default) protected routes answer 503.
3. **API host** — all workers on one machine; no second replica. The app is
   replica-safe (shared limiter store, no in-process job queue), so a second
   container behind the proxy is a configuration change, not a rewrite.
4. **Off-site backups** — not configured by default; the pgBackRest repo is a
   local volume unless the operator points it at object storage.
5. **Backup encryption key** — loss makes every backup unreadable; there is
   no escrow.
6. **Edge (TLS/proxy) and DNS** — one proxy container and owner-held accounts.
7. **LLM provider** — one configured provider; a fallback provider is
   optional configuration.

None of these is a surprise; what matters is that they are written down and
that the failure mode of each is "degraded or restore", never "silent
corruption".

## 6. Owner decisions (I10 — not decidable in this repository)

| # | Decision | Options | Cost/benefit |
|---|---|---|---|
| D1 | Database topology | (a) stay single-host; (b) managed PostgreSQL with standby + failover; (c) self-managed streaming replication | (a) today's RTO; (b) removes SPOF 1 and most of the restore risk; (c) cheaper licence, higher operator load |
| D2 | Multi-zone / multi-region | single zone (today) → 2 AZ with a standby → multi-region active/active | latency and cost grow with each step; for a national-scale education product, 2 AZ is the realistic first move |
| D3 | Off-site backup repo | (a) local volume only; (b) S3-compatible repo (`repo1-type=s3`); (c) rclone-sync of the volume | (b) is one stanza change plus credentials and a monthly restore check |
| D4 | Redis posture | (a) single instance with `FAIL_OPEN=false`; (b) managed with replica; (c) drop to in-process limits | (a) fails closed on outage; (c) loses cross-replica limits (auth abuse risk) |
| D5 | Key custody / escrow | (a) one operator holds the passphrase; (b) escrow with a second custodian | a single holder is a SPOF for recoverability |
| D6 | Corpus durability | (a) rebuild from source (current); (b) S3 copy + versioned manifest | rebuild is cheap today; (b) matters if the pipeline's sources change |

Until D1–D3 are answered, the honest description of the posture is:
**single-host, local-backup, restore-drilled**.

## 7. Escalation and ownership

- Backup failures: the sidecar logs `pgbackrest` errors; the compose health
  check and the `disk` alert in `deploy/prometheus/alerts.yml` cover the
  common causes (disk full, repo unreachable).
- Escalation contacts are the owner's, not this repository's; the owner
  action is to record them in the internal runbook (`docs/runbook.md` §support
  SLA lists what exists today).
- Every drill result is appended to §4 with the date, so "we tested DR" is
  never a claim without a line item.
