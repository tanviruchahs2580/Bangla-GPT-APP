"""DB-04/DB-05: age the answer log, index the budget-gate hot path

Revision ID: b5d7e9f1a3c7
Revises: a3c5e7f9b1d3
Create Date: 2026-10-27

Two data-layer findings from the 2026-10-27 audit, one reversible revision:

1. **answer_log had no timestamp at all.** It is the child's permanent
   academic record (one row per answered question, question_text up to
   2000 chars) that grows for the life of the account while the capacity
   plan claimed retention "bounds DB growth" -- the table could not be
   aged even if a policy existed. The column is added, then BACKFILLED
   from the parent attempt's created_at (every row's honest age), and the
   column is made NOT NULL afterwards; the backfilled domain gives every
   historical row the same purge policy as new ones. An index on the
   column serves the retention sweep's range scan.

2. **ai_usage lacked the composite the budget gate needs.**
   ``check_ai_budget`` runs ``SUM(cost) WHERE user_id=? AND created_at >=
   month_start`` on every generation; the existing separate user_id and
   created_at indexes made that a lifetime scan per account that grows
   forever. The composite (user_id, created_at) turns the hot-path query
   into an index range scan.

PostgreSQL takes plain ADD COLUMN + UPDATE (no table rewrite for a
nullable add; the NOT NULL conversion requires no table rewrite either
with a backfilled, PG-checked constraint set). SQLite re-creates the table
through alembic batch mode -- the answer_log table is small today; run
the same pattern on big tables only with the NOT VALID two-step noted in
the runbook. Every statement is reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5d7e9f1a3c7"
down_revision: str | Sequence[str] | None = "a3c5e7f9b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1a. the column, nullable first (a fresh column with NOT NULL would be
    #     a lie on SQLite batch mode anyway -- existing rows have no value).
    with op.batch_alter_table("answer_log") as batch:
        batch.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=True,
                # server-side default matches the model: raw-SQL writes get
                # timestamped too, not just ORM inserts.
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
    # 1b. backfill: the row's age is the attempt it belongs to. Correlated
    #     subquery form works identically on PostgreSQL and SQLite.
    op.execute(
        "UPDATE answer_log SET created_at = ("
        "  SELECT qa.created_at FROM quiz_attempts AS qa"
        "  WHERE qa.id = answer_log.attempt_id)"
    )
    # 1c. now the NOT NULL is a fact, not a promise.
    with op.batch_alter_table("answer_log") as batch:
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
    # 1d. the retention sweep's range scan needs this; the FK index on
    #     attempt_id answers the join direction, not the age filter.
    op.create_index("ix_answer_log_created_at", "answer_log", ["created_at"])

    # 2. the composite the budget gate sums over (see migration docstring).
    op.create_index(
        "ix_ai_usage_user_created",
        "ai_usage",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_user_created", table_name="ai_usage")
    op.drop_index("ix_answer_log_created_at", table_name="answer_log")
    with op.batch_alter_table("answer_log") as batch:
        batch.drop_column("created_at")
