"""A-xxx: indexable assignment membership (``assignment_recipients``).

Revision ID: c5d7e9f1a3b5
Revises: b4c6d8e0f2a4
Create Date: 2026-10-23

``GET /assignments/mine`` could not filter by student in SQL because
membership lived only inside ``Assignment.attempts`` JSON. It therefore took
the newest ``limit`` assignments *platform-wide* and filtered in Python: once
more than ``limit`` newer assignments existed anywhere on the platform, a
student's own older assignment silently disappeared from their hub while the
teacher side still showed it as outstanding.

This revision creates the membership relation and backfills it from the JSON
that already exists, so no assignment loses its recipients:

* ``assignment_recipients`` — (assignment_id, student_id, attempt_id), with a
  unique constraint per (assignment, student) and individual indexes on both
  foreign keys. The unique constraint means a re-run of the backfill cannot
  double-insert.
* Backfill parses ``assignments.attempts`` ({student_id, attempt_id} pairs)
  for every existing row. The migration reads raw SQL so it behaves
  identically on SQLite (JSON stored as TEXT) and PostgreSQL (JSON decoded by
  the driver); malformed entries are skipped rather than aborting the
  migration.

Writers dual-write (JSON + table) in one transaction until every reader has
moved; the JSON remains authoritative for progress displays that read it.
Fully reversible: the downgrade drops the table.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "c5d7e9f1a3b5"
down_revision: str | None = "b4c6d8e0f2a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assignment_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("quiz_attempts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("assignment_id", "student_id", name="uq_assignment_recipient"),
    )
    op.create_index(
        "ix_assignment_recipients_assignment_id", "assignment_recipients", ["assignment_id"]
    )
    op.create_index("ix_assignment_recipients_student_id", "assignment_recipients", ["student_id"])

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, attempts FROM assignments")).fetchall()
    inserts: list[dict[str, object]] = []
    # One naive-UTC timestamp for the whole backfill: ``created_at`` records
    # when the relation was materialised, not the original assignment time.
    # A live ``sa.func.now()`` cannot be used here — bulk_insert binds plain
    # values, and a SQL expression is not a bind value (the first version of
    # this migration failed on exactly that, caught by the backfill drill).
    backfilled_at = datetime.now(UTC).replace(tzinfo=None)
    for assignment_id, raw_attempts in rows:
        if isinstance(raw_attempts, str):
            try:
                attempts = json.loads(raw_attempts)
            except ValueError:
                continue
        else:
            attempts = raw_attempts or []
        if not isinstance(attempts, list):
            continue
        for entry in attempts:
            try:
                inserts.append(
                    {
                        "assignment_id": int(assignment_id),
                        "student_id": int(entry["student_id"]),
                        "attempt_id": int(entry["attempt_id"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                # An entry the writer could not have produced; skipping keeps
                # the migration from aborting on legacy junk.
                continue
    if inserts:
        table = sa.table(
            "assignment_recipients",
            sa.column("assignment_id", sa.Integer),
            sa.column("student_id", sa.Integer),
            sa.column("attempt_id", sa.Integer),
            sa.column("created_at", sa.DateTime),
        )
        # Chunked so a large history does not build one giant statement.
        chunk = 500
        for start in range(0, len(inserts), chunk):
            op.bulk_insert(
                table,
                [{**row, "created_at": backfilled_at} for row in inserts[start : start + chunk]],
            )


def downgrade() -> None:
    op.drop_index("ix_assignment_recipients_student_id", table_name="assignment_recipients")
    op.drop_index("ix_assignment_recipients_assignment_id", table_name="assignment_recipients")
    op.drop_table("assignment_recipients")
