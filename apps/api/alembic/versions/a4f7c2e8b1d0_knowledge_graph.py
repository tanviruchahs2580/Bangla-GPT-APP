"""knowledge graph v1: concepts, prerequisite edges, per-concept mastery

Revision ID: a4f7c2e8b1d0
Revises: d0e1f2a3b4c5
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4f7c2e8b1d0"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "concepts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("chapter", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", "class_level", "subject", name="uq_concept_identity"),
    )
    op.create_index("ix_concepts_name", "concepts", ["name"])
    op.create_index("ix_concepts_class_level", "concepts", ["class_level"])
    op.create_index("ix_concepts_subject", "concepts", ["subject"])
    op.create_table(
        "concept_prerequisites",
        sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concepts.id"), primary_key=True),
        sa.Column("prereq_id", sa.Integer(), sa.ForeignKey("concepts.id"), primary_key=True),
    )
    op.create_table(
        "concept_mastery",
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), primary_key=True),
        sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concepts.id"), primary_key=True),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("concept_mastery")
    op.drop_table("concept_prerequisites")
    op.drop_index("ix_concepts_subject", table_name="concepts")
    op.drop_index("ix_concepts_class_level", table_name="concepts")
    op.drop_index("ix_concepts_name", table_name="concepts")
    op.drop_table("concepts")
