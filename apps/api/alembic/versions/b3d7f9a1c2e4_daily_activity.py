"""daily_activity table for streak + heatmap (S1.9)

Revision ID: b3d7f9a1c2e4
Revises: a2c5e7b9d1f3
Create Date: 2026-09-06
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d7f9a1c2e4"
down_revision: Union[str, Sequence[str], None] = "a2c5e7b9d1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quizzes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("student_id", "date", name="uq_daily_activity_student_date"),
    )
    op.create_index("ix_daily_activity_student_id", "daily_activity", ["student_id"])
    op.create_index("ix_daily_activity_date", "daily_activity", ["date"])


def downgrade() -> None:
    op.drop_index("ix_daily_activity_date", table_name="daily_activity")
    op.drop_index("ix_daily_activity_student_id", table_name="daily_activity")
    op.drop_table("daily_activity")
