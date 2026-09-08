"""short tests: class+chapter ultra-fast classroom-wide tests

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-03

S2.5: short_tests stores one rule-based question set generated once per
assignment and handed to an entire classroom; grading reuses quiz_attempts
rows referenced in the attempts JSON. No backfill (new feature).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "short_tests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("classroom_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("chapter", sa.String(length=200), nullable=False),
        sa.Column("num_questions", sa.Integer(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["classroom_id"], ["classrooms.id"]),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_short_tests_classroom_id"), "short_tests", ["classroom_id"], unique=False
    )
    op.create_index(
        op.f("ix_short_tests_teacher_id"), "short_tests", ["teacher_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_short_tests_teacher_id"), table_name="short_tests")
    op.drop_index(op.f("ix_short_tests_classroom_id"), table_name="short_tests")
    op.drop_table("short_tests")
