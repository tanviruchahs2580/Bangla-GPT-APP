"""s1.2 chapter_progress

Revision ID: f1a2b3c4d5e6
Revises: d4e5f6a7b8c9
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "chapter_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("chapter", sa.String(length=200), nullable=False),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("read_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bookmarked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "subject", "chapter", "class_level", name="uq_chapter_progress"),
    )
    op.create_index(op.f("ix_chapter_progress_student_id"), "chapter_progress", ["student_id"], unique=False)

def downgrade() -> None:
    op.drop_index(op.f("ix_chapter_progress_student_id"), table_name="chapter_progress")
    op.drop_table("chapter_progress")
