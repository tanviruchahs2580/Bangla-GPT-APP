# DATABASE ARCHITECTURE — Bangla-GPT-APP

> **Date:** 2026-09-14
> **ORM:** SQLAlchemy 2.0
> **Migrations:** Alembic (20 migrations, head: a1b2c3d4e5f6 — append-only)

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

**Current migration head:** `a1b2c3d4e5f6` (append-only — no downgrade-safe deletions).

**Rules:**
- Never delete or modify existing migration files
- Always run `alembic upgrade head` in CI before tests
- Use `--autogenerate` only for simple schema changes (verify diff carefully)
- Complex data migrations must be written manually

---

## 5. Schema Overview

### Core Tables (from `db/models.py`)

| Table | Key Fields | Purpose |
|-------|-----------|---------|
| `user` | id, email, hashed_password, role, school_id | Auth + RBAC |
| `classroom` | id, school_id, class, section | School class structure |
| `conversation` | id, user_id, strategy | Chat history |
| `chat_message` | id, conversation_id, role, content, images | Message store |
| `quiz_attempt` | id, user_id, quiz_id, score | Quiz results |
| `audit_log` | id, user_id, action, entity, detail | Audit trail |
| `job_run` | id, type, status, result, created_at | Job state tracking |
| `parent_link` | id, parent_id, student_id, guardian_consent | Parent-child relationships |
| `event` | id, user_id, type, data | Activity tracking |

### Index Strategy

| Table | Index | Reason |
|-------|-------|--------|
| `user.email` | UNIQUE | Auth lookup |
| `conversation.user_id` | Non-unique | Query user conversations |
| `chat_message.conversation_id` | Non-unique | Load chat history |
| `quiz_attempt.user_id` | Non-unique | User quiz history |
| `audit_log.user_id` | Non-unique | User audit trail |
| `job_run.type + status` | Composite | Job claim/idempotency |
| `parent_link.parent_id` | Non-unique | Parent's children |
| `event.user_id + type` | Composite | Activity feed |

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
