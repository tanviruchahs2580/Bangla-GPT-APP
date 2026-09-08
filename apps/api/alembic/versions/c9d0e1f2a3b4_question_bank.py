"""question bank: reviewed questions with dedupe key for generation reuse

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-06

S2.9: question_bank stores every teacher-reviewed question keyed by a
deterministic sha256 over the normalized question text (the dedupe field),
plus a times_reused counter. No backfill (new feature); reviewed history
re-enters the bank naturally as teachers review new drafts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "question_bank",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("answer_index", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("chapter", sa.String(length=200), nullable=False),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("times_reused", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_question_bank_teacher_id"), "question_bank", ["teacher_id"], unique=False
    )
    op.create_index(
        op.f("ix_question_bank_dedupe_key"), "question_bank", ["dedupe_key"], unique=True
    )
    op.create_index(
        op.f("ix_question_bank_class_level"), "question_bank", ["class_level"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_question_bank_class_level"), table_name="question_bank")
    op.drop_index(op.f("ix_question_bank_dedupe_key"), table_name="question_bank")
    op.drop_index(op.f("ix_question_bank_teacher_id"), table_name="question_bank")
    op.drop_table("question_bank")
