"""bulk assignments: multi-student quiz assignment with due date tracking

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-03

S2.8: assignments stores one rule-based question set generated once per bulk
assignment plus the per-student quiz_attempts references; due_at drives the
completion/overdue list. No backfill (new feature).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("chapter", sa.String(length=200), nullable=False),
        sa.Column("num_questions", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assignments_teacher_id"), "assignments", ["teacher_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_assignments_teacher_id"), table_name="assignments")
    op.drop_table("assignments")
