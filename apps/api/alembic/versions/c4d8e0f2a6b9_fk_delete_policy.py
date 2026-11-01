"""F-014/DB-01: every foreign key declares its ON DELETE policy

Revision ID: c4d8e0f2a6b9
Revises: b5d7e9f1a3c7
Create Date: 2026-10-29

The audit (DB-01) found 52 foreign keys, zero with an ON DELETE action:
the erasure policy for DELETE /users/me lived only in application code, so
a child table the erasure path misses makes the delete fail with an
IntegrityError on PostgreSQL instead of cascading, and nothing at the
database level backed the "we delete everything" promise.

This revision gives every relationship an explicit policy that mirrors the
behaviour the application ALREADY implements (services/gdpr.py,
routers/users.py, services/retention.py):

* CASCADE -- rows owned by the referenced row, which the erasure path
  already deletes by hand (a profile's attempts, answers, conversations,
  messages, notes, documents, usage rows; a school's invites; an
  assignment's recipients; a concept's mastery rows). The database now
  finishes the job even if the code forgets a new child table.
* SET NULL -- an OPTIONAL pointer into a row whose deletion must not
  destroy the referencing row: the append-only audit trail, a shared
  chapter artifact outliving its author, a redeemed invite keeping its
  redemption facts, and product feedback on a message/attempt that was
  itself deleted (erasure and the retention sweep both null these today).
* NO ACTION -- deletion must be blocked rather than propagate silently:
  only the two tenancy roots (users.school_id, classrooms.school_id).
  Neither referenced row has a delete path in the product, so a school
  is never removed while staff or classrooms still point at it; the
  operator has to move them explicitly first. (NO ACTION is also the
  current default, so this pair keeps today's behaviour.)

Nothing here changes an application query. The database gains a second
wall behind the erasure code: a manual delete of a users row now removes
(and refuses to orphan) the same rows DELETE /users/me does, and a
primary-key-preserving data import cannot leave dangling children behind.

Portability: SQLite cannot ALTER a foreign key, so those tables are
rebuilt with the DDL the database itself holds -- the stored CREATE TABLE
is read, each FOREIGN KEY clause is matched and given the trailing
"ON DELETE <action>", the table is recreated under a temporary name, rows
are copied BY COLUMN NAME, the old table is dropped, the table is renamed
back, and the stored indexes are recreated. CHECK constraints, UNIQUE
constraints, defaults and column types are therefore carried over
byte-for-byte from the existing schema instead of being re-derived.
PostgreSQL needs no rewrite: the existing constraint is dropped and
re-created with the same name and the policy added.

Requirement: the SQLite rebuild must run with foreign-key enforcement OFF
at the connection level (the SQLAlchemy default, so `alembic upgrade`
already satisfies it). The rebuild raises rather than proceeding if
PRAGMA foreign_keys is ON, because a DROP TABLE under enforcement would
either fail on the dependent rows or fire their ON DELETE actions -- the
one way this migration could destroy data.

Every statement is reversible: the downgrade restores ON DELETE NO ACTION.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e0f2a6b9"
down_revision: str | Sequence[str] | None = "b5d7e9f1a3c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CASCADE = "CASCADE"
SET_NULL = "SET NULL"
NO_ACTION = "NO ACTION"

#: table -> {local column names: policy}. Every foreign key in
#: bangla_gpt_api.db.models is listed; tests/test_w2_db_fk_policy.py pins
#: the models against this map so a new FK cannot ship policy-free.
FK_POLICY: dict[str, dict[tuple[str, ...], str]] = {
    "users": {("school_id",): NO_ACTION},
    "password_resets": {("user_id",): CASCADE},
    "students": {("user_id",): CASCADE},
    "teachers": {("user_id",): CASCADE},
    "parents": {("user_id",): CASCADE},
    "parent_student_links": {("parent_id",): CASCADE, ("student_id",): CASCADE},
    "quiz_attempts": {("student_id",): CASCADE},
    "answer_log": {("attempt_id",): CASCADE},
    "email_verifications": {("user_id",): CASCADE},
    "conversations": {("student_id",): CASCADE},
    "chat_messages": {("conversation_id",): CASCADE},
    "parent_invites": {("student_id",): CASCADE, ("used_by_parent_id",): SET_NULL},
    "feedback": {
        ("user_id",): CASCADE,
        ("message_id",): SET_NULL,
        ("attempt_id",): SET_NULL,
    },
    "chapter_progress": {("student_id",): CASCADE},
    "daily_activity": {("student_id",): CASCADE},
    "revision_queue": {("student_id",): CASCADE},
    "classrooms": {("school_id",): NO_ACTION},
    "class_students": {("classroom_id",): CASCADE, ("student_id",): CASCADE},
    "class_teachers": {("classroom_id",): CASCADE, ("teacher_id",): CASCADE},
    "student_invites": {("classroom_id",): CASCADE, ("student_id",): CASCADE},
    "chapter_contents": {("created_by",): SET_NULL},
    "question_papers": {("teacher_id",): CASCADE},
    "short_tests": {("classroom_id",): CASCADE, ("teacher_id",): CASCADE},
    "support_plans": {("student_id",): CASCADE, ("teacher_id",): CASCADE},
    "assignments": {("teacher_id",): CASCADE},
    "assignment_recipients": {
        ("assignment_id",): CASCADE,
        ("student_id",): CASCADE,
        ("attempt_id",): CASCADE,
    },
    "question_bank": {("teacher_id",): CASCADE},
    "school_invites": {
        ("school_id",): CASCADE,
        ("created_by",): CASCADE,
        ("used_by",): SET_NULL,
    },
    "concept_prerequisites": {("concept_id",): CASCADE, ("prereq_id",): CASCADE},
    "concept_mastery": {("student_id",): CASCADE, ("concept_id",): CASCADE},
    "student_abilities": {("student_id",): CASCADE},
    "audit_log": {("actor_user_id",): SET_NULL},
    "teacher_documents": {("teacher_id",): CASCADE},
    "saved_notes": {("user_id",): CASCADE},
    "notifications": {("user_id",): CASCADE},
    "ai_jobs": {("user_id",): CASCADE},
    "ai_usage": {("user_id",): CASCADE},
}

#: PostgreSQL confdeltype codes, used by the post-migration assertion.
_PG_DELTYPE = {"a": NO_ACTION, "r": "RESTRICT", "c": CASCADE, "n": SET_NULL, "d": "SET DEFAULT"}

#: SQLite rebuild scratch name. Prefix marks tables this migration owns.
_TMP_PREFIX = "_fk_policy_tmp_"

_FK_CLAUSE = re.compile(
    r"FOREIGN\s+KEY\s*\((?P<cols>[^)]*)\)\s*"
    r"REFERENCES\s+(?P<ref>[A-Za-z0-9_\"\[\]`]+)\s*\((?P<refcols>[^)]*)\)"
    r"(?P<action>\s+ON\s+DELETE\s+[A-Za-z ]+?)?"
    r"(?=\s*(?:,|\)\s*$))",
    re.IGNORECASE | re.DOTALL,
)


def _ident_list(raw: str) -> tuple[str, ...]:
    return tuple(part.strip().strip('"[]`') for part in raw.split(",") if part.strip())


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table, policy in FK_POLICY.items():
            _pg_set_policy(table, policy, apply=True)
    else:
        _require_sqlite_enforcement_off()
        trigger_names = _sqlite_trigger_names()
        for table, policy in FK_POLICY.items():
            _sqlite_set_policy(table, policy, strip=False)
        _recreate_sqlite_triggers(trigger_names)
        _assert_sqlite_policies()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table, policy in FK_POLICY.items():
            _pg_set_policy(table, policy, apply=False)
    else:
        _require_sqlite_enforcement_off()
        trigger_names = _sqlite_trigger_names()
        for table, policy in FK_POLICY.items():
            _sqlite_set_policy(table, policy, strip=True)
        _recreate_sqlite_triggers(trigger_names)


# --- PostgreSQL ------------------------------------------------------------


def _pg_foreign_keys(table: str) -> list[dict[str, object]]:
    rows = op.get_bind().execute(
        sa.text(
            """
            SELECT c.conname AS name,
                   c.confdeltype AS deltype,
                   (
                       SELECT string_agg(a.attname, ',' ORDER BY k.ord)
                       FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                       JOIN pg_attribute a
                         ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                   ) AS cols,
                   rt.relname AS ref_table,
                   (
                       SELECT string_agg(a.attname, ',' ORDER BY k.ord)
                       FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
                       JOIN pg_attribute a
                         ON a.attrelid = c.confrelid AND a.attnum = k.attnum
                   ) AS ref_cols
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_class rt ON rt.oid = c.confrelid
            WHERE t.relname = :table AND c.contype = 'f'
            ORDER BY c.conname
            """
        ),
        {"table": table},
    ).mappings()
    return [dict(row) for row in rows]


def _pg_set_policy(table: str, policy: dict[tuple[str, ...], str], *, apply: bool) -> None:
    """Drop and re-create each FK with the policy (or plain NO ACTION)."""
    found = _pg_foreign_keys(table)
    by_columns = {_ident_list(str(row["cols"])): row for row in found}
    missing = sorted(cols for cols in policy if cols not in by_columns)
    if missing:
        raise RuntimeError(f"{table}: foreign keys not found for {missing}")
    for cols, action in policy.items():
        row = by_columns[cols]
        name = str(row["name"])
        want = action if apply else None
        if str(row["deltype"]) == _pg_deltype_code(action) and apply:
            continue
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name,
            table,
            str(row["ref_table"]),
            list(cols),
            list(_ident_list(str(row["ref_cols"]))),
            ondelete=want,
        )


def _pg_deltype_code(action: str) -> str:
    for code, label in _PG_DELTYPE.items():
        if label == action:
            return code
    raise RuntimeError(f"unknown policy {action!r}")


# --- SQLite ----------------------------------------------------------------


def _require_sqlite_enforcement_off() -> None:
    if int(op.get_bind().exec_driver_sql("PRAGMA foreign_keys").scalar() or 0) != 0:
        raise RuntimeError(
            "the FK policy migration rebuilds tables and must run with "
            "PRAGMA foreign_keys=OFF (the SQLAlchemy default); re-run "
            "migrations on a connection without the pragma enabled"
        )


def _sqlite_trigger_names() -> list[str]:
    return [
        str(row[0])
        for row in op.get_bind()
        .exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        .fetchall()
    ]


def _recreate_sqlite_triggers(names: list[str]) -> None:
    """DROP TABLE drops the table's triggers; recreate the dropped ones.

    None ship today (checked by tests/test_w2_db_fk_policy.py), but a
    deployment that added a trigger of its own must not lose it to this
    migration.
    """
    for name in names:
        row = (
            op.get_bind()
            .exec_driver_sql("SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?", (name,))
            .fetchone()
        )
        if row is not None and row[0]:
            op.get_bind().exec_driver_sql(str(row[0]))


def _sqlite_set_policy(table: str, policy: dict[tuple[str, ...], str], *, strip: bool) -> None:
    bind = op.get_bind()
    row = bind.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None or not row[0]:
        raise RuntimeError(f"{table}: table DDL not found")
    ddl = str(row[0])
    if _TMP_PREFIX in ddl:
        raise RuntimeError(f"{table}: previous rebuild left a temporary table behind")

    rewritten, seen = _rewrite_fk_clauses(ddl, policy, strip=strip)
    if set(seen) != set(policy):
        raise RuntimeError(f"{table}: DDL carries FKs {sorted(seen)}, policy expects {sorted(policy)}")

    columns = [
        str(r[1]) for r in bind.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()
    ]
    index_sql = [
        str(r[0])
        for r in bind.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
            (table,),
        ).fetchall()
    ]
    tmp = f"{_TMP_PREFIX}{table}"
    # CREATE TABLE holds the whole statement; only the name is substituted.
    body = rewritten.split("(", 1)[1]
    quoted = ", ".join(f'"{c}"' for c in columns)
    bind.exec_driver_sql(f'CREATE TABLE "{tmp}" ({body}')
    bind.exec_driver_sql(f'INSERT INTO "{tmp}" ({quoted}) SELECT {quoted} FROM "{table}"')
    bind.exec_driver_sql(f'DROP TABLE "{table}"')
    bind.exec_driver_sql(f'ALTER TABLE "{tmp}" RENAME TO "{table}"')
    for sql in index_sql:
        bind.exec_driver_sql(sql)


def _rewrite_fk_clauses(
    ddl: str, policy: dict[tuple[str, ...], str], *, strip: bool
) -> tuple[str, set[tuple[str, ...]]]:
    """Give every FOREIGN KEY clause the policy's ON DELETE (or strip it)."""
    seen: set[tuple[str, ...]] = set()
    table_actions = {cols: (None if strip else action) for cols, action in policy.items()}

    def replace(match: re.Match[str]) -> str:
        cols = _ident_list(match.group("cols"))
        head = ddl[match.start() : match.end() - len(match.group("action") or "")]
        seen.add(cols)
        if cols not in table_actions:
            raise RuntimeError(f"unlisted foreign key {cols} in {ddl[:60]!r}")
        action = table_actions[cols]
        if action is None:
            return head
        return f"{head} ON DELETE {action}"

    return _FK_CLAUSE.sub(replace, ddl), seen


def _assert_sqlite_policies() -> None:
    """Read the policies back from PRAGMA; the rebuild is only done if they hold."""
    bind = op.get_bind()
    for table, policy in FK_POLICY.items():
        # PRAGMA foreign_key_list row: id, seq, table, from, to, on_update,
        # on_delete, match -- a composite FK spans several rows, none exist here.
        by_columns = {
            (str(row[3]),): str(row[6])
            for row in bind.exec_driver_sql(f'PRAGMA foreign_key_list("{table}")').fetchall()
        }
        for cols, action in policy.items():
            got = by_columns.get(cols)
            if got != action:
                raise RuntimeError(f"{table}{cols}: expected ON DELETE {action}, found {got}")
