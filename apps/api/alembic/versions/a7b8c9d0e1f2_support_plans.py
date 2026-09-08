"""support plans: three-week rule-based plans for at-risk students

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-03

S2.7: support_plans stores the deterministic 3-week structure (concept ->
practice -> assessment) generated from a student's weakest concepts. No
backfill (new feature).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("focus_concepts", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_support_plans_student_id"), "support_plans", ["student_id"], unique=False
    )
    op.create_index(
        op.f("ix_support_plans_teacher_id"), "support_plans", ["teacher_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_support_plans_teacher_id"), table_name="support_plans")
    op.drop_index(op.f("ix_support_plans_student_id"), table_name="support_plans")
    op.drop_table("support_plans")
