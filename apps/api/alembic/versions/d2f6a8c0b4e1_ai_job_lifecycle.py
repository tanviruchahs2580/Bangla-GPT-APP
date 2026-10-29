"""F-007: the ai_jobs row becomes an idempotency record and counts attempts

Revision ID: d2f6a8c0b4e1
Revises: c4d8e0f2a6b9
Create Date: 2026-10-29

Two additive columns for the AI-job lifecycle finding (BE-17):

* ``idempotency_key`` -- the optional ``Idempotency-Key`` header value a
  caller sends on POST /teacher/jobs. Together with ``user_id`` and
  ``kind`` it forms the unique index ``uq_ai_jobs_idempotency``, so a
  double-click or a client retry returns the SAME job (and pays for one
  provider generation) instead of creating a second one. NULL is exempt
  from the uniqueness by SQL semantics, so callers that do not send the
  header are unaffected.

* ``attempts`` -- how many times the runner executed the job. 1 for a
  first-try success; more when a transient provider failure was retried
  under the bounded job-level retry plan. Shipped with a server default so
  existing rows (and raw-SQL writers) are dated honestly.

Both statements are plain ADD COLUMN + CREATE [UNIQUE] INDEX, which SQLite
supports without a table rebuild and PostgreSQL without a rewrite; the
downgrade drops the index and both columns. Reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f6a8c0b4e1"
down_revision: str | Sequence[str] | None = "c4d8e0f2a6b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_jobs",
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "uq_ai_jobs_idempotency",
        "ai_jobs",
        ["user_id", "kind", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_ai_jobs_idempotency", table_name="ai_jobs")
    op.drop_column("ai_jobs", "attempts")
    op.drop_column("ai_jobs", "idempotency_key")
