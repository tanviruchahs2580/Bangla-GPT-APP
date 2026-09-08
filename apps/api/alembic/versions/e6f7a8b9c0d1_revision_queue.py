"""revision_queue table for SM-2-lite spaced revision (S1.10)

Revision ID: e6f7a8b9c0d1
Revises: b3d7f9a1c2e4
Create Date: 2026-09-06
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "b3d7f9a1c2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revision_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("correct_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chapter", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("subject", sa.String(length=60), nullable=True),
        sa.Column("class_level", sa.Integer(), nullable=True),
        sa.Column("reps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ease_factor", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("due_date", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "student_id", "question", name="uq_revision_queue_student_question"
        ),
    )
    op.create_index("ix_revision_queue_student_id", "revision_queue", ["student_id"])
    op.create_index("ix_revision_queue_due_date", "revision_queue", ["due_date"])


def downgrade() -> None:
    op.drop_index("ix_revision_queue_due_date", table_name="revision_queue")
    op.drop_index("ix_revision_queue_student_id", table_name="revision_queue")
    op.drop_table("revision_queue")
