"""teacher-in-the-loop question papers (draft -> review -> final)

Revision ID: e5f6a7b8c9d0
Revises: c1d2e3f4a5b6
Create Date: 2026-09-06

S2.4: question_papers stores exam paper drafts and finals with their
validated question sets and review timestamps. No backfill (new feature).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "question_papers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("exam_type", sa.String(length=40), nullable=False),
        sa.Column("marks", sa.Integer(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.JSON(), nullable=False),
        sa.Column("chapters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_question_papers_teacher_id"), "question_papers", ["teacher_id"], unique=False
    )
    op.create_index(
        op.f("ix_question_papers_status"), "question_papers", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_question_papers_status"), table_name="question_papers")
    op.drop_index(op.f("ix_question_papers_teacher_id"), table_name="question_papers")
    op.drop_table("question_papers")
