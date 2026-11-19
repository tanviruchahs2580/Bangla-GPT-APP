"""T-20/BC-5: indexable attempt-membership link tables + JSON backfill.

Revision ID: e2f3a4b5c6d7
Revises: c7d9e1f3a5b7
Create Date: 2026-11-20

The ``assignments.attempts`` and ``short_tests.attempts`` JSON arrays hold
``[{student_id, attempt_id}]`` records that progress reads scan in Python and
then resolve with a second ``IN`` query (assessment.py). This migration adds
the queryable mirror tables, backfills them from the JSON history, and
leaves the JSON columns untouched — reads move behind the
``ATTEMPT_LINKS_READ`` setting whose default keeps the JSON path
(expand/contract; the JSON column drops in a later release).

Reversibility: downgrade drops the mirror tables only; the JSON data they
were derived from is never modified, so a downgrade loses no information.

The backfill is idempotent and resumable: it re-derives rows from the JSON
and inserts with conflict-ignoring semantics (ON CONFLICT DO NOTHING on
PostgreSQL, OR IGNORE on SQLite), batched per parent id, so a re-run after
a partial application converges on the same end state.
"""

from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "c7d9e1f3a5b7"
branch_labels: str | None = None
depends_on: str | None = None

_TABLES = (
    # assignments already have their indexed mirror (assignment_recipients,
    # migration c5d7e9f1a3b5 — created AND backfilled there), so this
    # migration only adds the missing short-test mirror.
    {
        "name": "short_test_attempt_links",
        "parent": "short_tests",
        "parent_fk": "short_test_id",
        "unique": "uq_short_test_attempt_links_short_test_student",
    },
)


def _link_table(name: str, parent: str, parent_fk: str, unique: str) -> sa.Table:
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(parent_fk, sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint([parent_fk], [f"{parent}.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["quiz_attempts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(parent_fk, "student_id", name=unique),
    )


def _json_refs(value: Any) -> list[tuple[int, int]]:
    """The (student_id, attempt_id) pairs a JSON attempts array names.

    Malformed entries are skipped rather than aborting the backfill: the JSON
    stays the read path until the reconciliation check passes, so a broken
    row degrades to "not mirrored" instead of "migration failed".
    """
    out: list[tuple[int, int]] = []
    if not isinstance(value, list):
        return out
    for entry in value:
        try:
            out.append((int(entry["student_id"]), int(entry["attempt_id"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _backfill(bind: sa.Connection, table: sa.Table, parent: str, parent_fk: str) -> int:
    """Re-derive link rows from the JSON history, conflict-ignoring, batched."""
    total = 0
    parent_ids = [
        row[0]
        for row in bind.execute(
            # {parent} is a module constant from _TABLES, never request data
            sa.text(f"SELECT id FROM {parent} ORDER BY id")  # noqa: S608
        ).fetchall()
    ]
    for chunk_start in range(0, len(parent_ids), 200):
        chunk = parent_ids[chunk_start : chunk_start + 200]
        rows: list[dict[str, int]] = []
        for pid in chunk:
            # see the constant-name note above: {parent} is one of the two
            # fixed table names in _TABLES, never request data.
            raw = bind.execute(
                # {parent} is a module constant from _TABLES, never request data
                sa.text(f"SELECT attempts FROM {parent} WHERE id = :pid"),  # noqa: S608
                {"pid": pid},
            ).scalar_one_or_none()
            for sid, aid in _json_refs(raw):
                rows.append({parent_fk: pid, "student_id": sid, "attempt_id": aid})
        if not rows:
            continue
        # conflict-ignoring insert: re-running the migration converges
        dialect = bind.dialect.name
        if dialect == "postgresql":
            pk = [parent_fk, "student_id"]
            insert = sa.pg_insert(table).on_conflict_do_nothing(index_elements=pk)
            bind.execute(insert, rows)
        else:
            insert = table.insert()
            for row in rows:
                # conflict-ignore IS the documented idempotency contract of the
                # backfill; suppress() hides the branch less clearly
                try:  # noqa: SIM105
                    bind.execute(insert, row)
                except sa.exc.IntegrityError:
                    pass
        total += len(rows)
    return total


def upgrade() -> None:
    bind = op.get_bind()
    for spec in _TABLES:
        table = _link_table(spec["name"], spec["parent"], spec["parent_fk"], spec["unique"])
        op.create_table(
            spec["name"],
            *[
                sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column(spec["parent_fk"], sa.Integer(), nullable=False),
                sa.Column("student_id", sa.Integer(), nullable=False),
                sa.Column("attempt_id", sa.Integer(), nullable=False),
            ],
            sa.ForeignKeyConstraint(
                [spec["parent_fk"]], [f"{spec['parent']}.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["attempt_id"], ["quiz_attempts.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(spec["parent_fk"], "student_id", name=spec["unique"]),
        )
        op.create_index(f"ix_{spec['name']}_{spec['parent_fk']}", spec["name"], [spec["parent_fk"]])
        op.create_index(f"ix_{spec['name']}_student_id", spec["name"], ["student_id"])
        op.create_index(f"ix_{spec['name']}_attempt_id", spec["name"], ["attempt_id"])
        _backfill(bind, table, spec["parent"], spec["parent_fk"])


def downgrade() -> None:
    for spec in reversed(_TABLES):
        op.drop_index(f"ix_{spec['name']}_attempt_id", table_name=spec["name"])
        op.drop_index(f"ix_{spec['name']}_student_id", table_name=spec["name"])
        op.drop_index(f"ix_{spec['name']}_{spec['parent_fk']}", table_name=spec["name"])
        op.drop_table(spec["name"])
