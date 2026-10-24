"""Indexes for the grade-filtered hot paths (audit L-11).

Revision ID: d6e8f2a4b6c8
Revises: c5d7e9f1a3b5
Create Date: 2026-10-23

Two columns are filtered on hot paths but had no index:

* ``students.class_level`` — roster loads filter by grade
  (``_load_class_students``); without the index every class page full-scans
  the students table.
* ``chapter_contents.class_level`` — ``school_coverage`` filters by grade in
  one pass; same full-scan shape on an append-only table that only grows.

Both indexes are pure performance: no column is added or changed, the
downgrade simply drops them.

Revision ID: d6e8f2a4b6c8
Revises: c5d7e9f1a3b5
"""

from alembic import op

revision: str = "d6e8f2a4b6c8"
down_revision: str | None = "c5d7e9f1a3b5"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(op.f("ix_students_class_level"), "students", ["class_level"], unique=False)
    op.create_index(
        op.f("ix_chapter_contents_class_level"),
        "chapter_contents",
        ["class_level"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chapter_contents_class_level"), table_name="chapter_contents")
    op.drop_index(op.f("ix_students_class_level"), table_name="students")
