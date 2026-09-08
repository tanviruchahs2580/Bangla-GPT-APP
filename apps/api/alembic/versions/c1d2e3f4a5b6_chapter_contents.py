"""versioned AI chapter content (content engine)

Revision ID: c1d2e3f4a5b6
Revises: b9c0d1e2f3a4
Create Date: 2026-09-06

S2.3: chapter_contents stores append-only versions of generated chapter
study material. One AI call fills all seven section keys of the JSON
payload; teacher edits append a new version instead of mutating rows.
No backfill (new feature).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chapter_contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("chapter", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subject",
            "class_level",
            "chapter",
            "version",
            name="uq_chapter_content_version",
        ),
    )
    op.create_index(
        op.f("ix_chapter_contents_subject"), "chapter_contents", ["subject"], unique=False
    )
    op.create_index(
        op.f("ix_chapter_contents_chapter"), "chapter_contents", ["chapter"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chapter_contents_chapter"), table_name="chapter_contents")
    op.drop_index(op.f("ix_chapter_contents_subject"), table_name="chapter_contents")
    op.drop_table("chapter_contents")
