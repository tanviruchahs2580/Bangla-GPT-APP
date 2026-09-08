"""job_runs idempotency ledger (S5.4 background jobs)

Revision ID: e8f9a0b1c2d3
Revises: c7d1e4f6a2b8
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "c7d1e4f6a2b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("job", sa.String(length=80), nullable=False),
        sa.Column("period_key", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("job", "period_key"),
    )


def downgrade() -> None:
    op.drop_table("job_runs")
