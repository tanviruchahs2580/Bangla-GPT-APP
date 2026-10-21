# DATABASE ARCHITECTURE — Bangla-GPT-APP

> **Date:** 2026-09-14
> **ORM:** SQLAlchemy 2.0
> **Migrations:** Alembic (append-only). The revision files in
> `apps/api/alembic/versions/` are the source of truth for the current head —
> run `alembic heads` from `apps/api/` to print it.

---

## 1. Development Database

| Setting | Value |
|---------|-------|
| Default | `sqlite:///./bangla_gpt.db` (file-based) |
| Purpose | Local development, data persists across restarts |
| Config | `DATABASE_URL` env var |

In-memory (`sqlite://` / `sqlite:///:memory:`) is **refused in production** via `enforce_production_safety()` and `validate_database_url()`.

---

## 2. Staging Database

| Setting | Value |
|---------|-------|
| Default | `postgresql+psycopg://bgpt:bgpt@staging-db:5432/bgpt_staging` |
| Purpose | Pre-production validation |
| Isolation | Separate schema or separate database from prod |

---

## 3. Production Database

| Setting | Value |
|---------|-------|
| Default | `postgresql+psycopg://bgpt:bgpt@prod-db:5432/bgpt` |
| Purpose | Production workloads |
| Connection pooling | SQLAlchemy `QueuePool` (default) or `AsyncEngine` for async |
| Max connections | `WEB_CONCURRENCY * 2` (recommend 2x worker count) |
| SSL | Required for hosted PostgreSQL (RDS, Cloud SQL, etc.) |

---

## 4. Migration Process

```bash
# Create new migration
alembic revision --autogenerate -m "description of change"

# Apply to any environment
ALEMBIC_CONFIG=alembic.ini DATABASE_URL=<url> alembic upgrade head

# Rollback one step
alembic downgrade -1

# Full cycle (verified in CI)
alembic upgrade head && alembic downgrade base && alembic upgrade head
```

**Current migration head:** the repository has a single head; it moves with
every new revision, so the authoritative answer is the command

```bash
cd apps/api && alembic heads        # prints "<revision> (head)"
```

(append-only — no downgrade-safe deletions).

**Rules:**

- Never delete or modify existing migration files
- Always run `alembic upgrade head` in CI before tests
- Use `--autogenerate` only for simple schema changes (verify diff carefully)
- Complex data migrations must be written manually

---

## 5. Schema Overview

### Core Tables (from `db/models.py`)

Curated overview; `apps/api/src/bangla_gpt_api/db/models/` is authoritative and
also defines the remaining domain tables (assignments, question banks,
short tests, question papers, chapter content, revision queue, notifications,
AI jobs/usage, …).

| Table | Key Fields | Purpose |
|-------|-----------|---------|
| `users` | id, email (unique), password_hash, role, school_id, email_verified, totp_secret, sessions_invalidated_at, failed_login_count, locked_until | Auth + RBAC |
| `students` | id, user_id, name, class_level, learning_prefs, memory_enabled, consent_ip/consent_at/consent_version | Student profile + guardian-consent evidence |
| `teachers` / `parents` | id, user_id, name (+ `parents.phone_enc`, encrypted) | Role profiles |
| `schools` | id, name, code (unique) | School tenancy root |
| `classrooms` | id, school_id, class_level, section (unique per school+level+section) | School class structure |
| `class_students` / `class_teachers` | classroom_id + student_id / teacher_id, subject | Enrollment, teacher assignment |
| `conversations` | id, student_id, title, last_strategy | Tutoring chat sessions |
| `chat_messages` | id, conversation_id, role, content, grounded, refused_reason, sources_json, rating | Message store |
| `quiz_attempts` | id, student_id, subject, class_level, status, total, correct, score_pct, quiz_json | Quiz results |
| `answer_log` | id, attempt_id, question_text, chosen, correct_index, is_correct, chapter, book | Per-question answer trail |
| `parent_student_links` | id, parent_id, student_id (unique pair) | Parent–child relationships (consent lives on `students`) |
| `audit_log` | id, created_at, actor_user_id, actor_role, action, target, detail | Privileged-action audit trail |
| `job_runs` | job, period_key (composite PK), started_at, finished_at, outcome | Scheduled-job claim/idempotency |
| `analytics_events` | id, user_id (no FK), name, role, props | Privacy-safe activity tracking |

### Index Strategy

| Table | Index | Reason |
|-------|-------|--------|
| `users.email` | UNIQUE | Auth lookup |
| `users.school_id` | Non-unique | Tenant scoping |
| `students.user_id` | UNIQUE | Profile lookup |
| `conversations.student_id` | Non-unique | Query a student's conversations |
| `chat_messages.conversation_id` | Non-unique | Load chat history |
| `quiz_attempts.student_id` | Non-unique | Student quiz history |
| `audit_log.actor_user_id`, `audit_log.action` | Non-unique | Audit queries |
| `job_runs (job, period_key)` | Composite primary key | Job claim/idempotency |
| `parent_student_links.parent_id` / `.student_id` | Non-unique | Parent's children, student's guardians |
| `analytics_events.user_id` / `.created_at` | Non-unique | Activity feed |

---

## 6. Transaction Integrity

- All write operations use explicit `Session.commit()` within try/except blocks
- `rollback()` on any exception
- `init_db()` creates tables automatically in dev (SQLAlchemy `Base.metadata.create_all`)
- Foreign keys enforced at DB level where possible
- `nullable=False` on required fields (email, role, etc.)

---

## 7. Backup Strategy

| Strategy | Tool | Frequency | Retention |
|----------|------|-----------|-----------|
| Full DB backup | pgBackRest | Nightly | 14 days |
| WAL archiving | pgBackRest | Continuous | Until consumed |
| Off-site storage | S3-compatible | With pgBackRest | Same as local |

**pgBackRest config:** `deploy/postgres/pgbackrest.conf`

**Recovery scripts:**

- `scripts/pg_backup.sh` — manual backup trigger
- `scripts/pgbackrest_drill.sh` — DR drill
- `scripts/restore_test.py` — verify restore integrity

---

## 8. Restore Strategy

```bash
# 1. Stop application
# 2. Restore from backup
pgbackrest --repo=/backups/pgbackrest restore --type=time \
  --target="2026-09-14 12:00:00 +06"

# 3. Verify data integrity
python scripts/restore_test.py

# 4. Point DATABASE_URL to restored DB
# 5. Run alembic upgrade head (if needed)
# 6. Restart application
```

---

## 9. Connection Pooling

| Environment | Strategy |
|-------------|----------|
| Dev | SQLAlchemy default `QueuePool` ( SQLite — no pool needed) |
| Staging | `QueuePool(max_overflow=10, pool_size=5)` |
| Production | External: PgBouncer or Cloud SQL Proxy |

---

## 10. Data Provenance

NCTB corpus data includes full provenance tracking via `curriculum/models.CurriculumMeta`:

- `curriculum_year` — academic year
- `class_level` — 1 through 12
- `subject` — subject name
- `book` — book identifier
- `chapter` — chapter number
- `section` — section within chapter
- `page` — page number
- `language` — bn / en
- `source` — source reference
- `version` — corpus version string
- `content_type` — text / structured

Every retrieval chunk keeps its metadata; answers are traceable to source chunks → documents → version.
