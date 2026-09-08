"""adaptive practice: Elo item difficulty + per-concept student ability

Revision ID: c7d1e4f6a2b8
Revises: a4f7c2e8b1d0
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d1e4f6a2b8"
down_revision: str | None = "a4f7c2e8b1d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "practice_items",
        sa.Column("fingerprint", sa.String(length=16), primary_key=True),
        sa.Column("chapter", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("elo", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_practice_items_subject", "practice_items", ["subject"])
    op.create_index("ix_practice_items_class_level", "practice_items", ["class_level"])
    op.create_table(
        "student_abilities",
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), primary_key=True),
        sa.Column("concept", sa.String(length=200), primary_key=True),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("ability", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_student_abilities_class_level", "student_abilities", ["class_level"])


def downgrade() -> None:
    op.drop_index("ix_student_abilities_class_level", table_name="student_abilities")
    op.drop_table("student_abilities")
    op.drop_index("ix_practice_items_class_level", table_name="practice_items")
    op.drop_index("ix_practice_items_subject", table_name="practice_items")
    op.drop_table("practice_items")
