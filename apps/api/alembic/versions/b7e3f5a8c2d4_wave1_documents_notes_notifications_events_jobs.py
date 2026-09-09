"""backend wave 1: documents, notes, notifications, analytics events, ai jobs

Revision ID: b7e3f5a8c2d4
Revises: a1b2c3d4e5f6
Create Date: 2026-09-08

Five additive tables plus three additive columns, all fully reversible:

* ``teacher_documents``  persisted outputs of the generic teacher generators
  (lesson_plan / worksheet / answer_key / homework / rubric).
* ``saved_notes``        user notes clipped from tutor/chapter/other.
* ``notifications``      i18n-code notification feed (never final copy).
* ``analytics_events``   sanitized product-event trail. ``user_id`` is
  deliberately an INDEXED plain INT with NO FK: the trail is append-only
  privacy history removed by the retention sweep, so it must neither block
  nor be blocked by account deletion.
* ``ai_jobs``            async generation jobs (queued -> generating ->
  validating -> ready | failed).

* ``students.learning_prefs`` / ``students.memory_enabled`` and
  ``teachers.prefs`` are additive columns with server defaults, so existing
  rows keep working unchanged.

Every user-FK child table here is also cleaned in DELETE /users/me
(BUG-4 FK-completeness rule).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e3f5a8c2d4"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "teacher_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("class_level", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("chapter", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_teacher_documents_teacher_id"), "teacher_documents", ["teacher_id"]
    )
    op.create_index(
        op.f("ix_teacher_documents_created_at"), "teacher_documents", ["created_at"]
    )

    op.create_table(
        "saved_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_saved_notes_user_id"), "saved_notes", ["user_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("link", sa.String(length=200), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"])
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"])

    # NOTE: analytics_events.user_id is an indexed plain INT on purpose -- no
    # FK. The trail is append-only privacy history cleaned by the retention
    # sweep; a FK here would let analytics rows silently block account
    # deletion (BUG-4 class of bug, inverted).
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column("props", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analytics_events_user_id"), "analytics_events", ["user_id"])
    op.create_index(op.f("ix_analytics_events_created_at"), "analytics_events", ["created_at"])

    op.create_table(
        "ai_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_jobs_user_id"), "ai_jobs", ["user_id"])

    op.add_column("students", sa.Column("learning_prefs", sa.JSON(), nullable=True))
    op.add_column(
        "students",
        sa.Column(
            "memory_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column("teachers", sa.Column("prefs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("teachers", "prefs")
    op.drop_column("students", "memory_enabled")
    op.drop_column("students", "learning_prefs")

    op.drop_index(op.f("ix_ai_jobs_user_id"), table_name="ai_jobs")
    op.drop_table("ai_jobs")

    op.drop_index(op.f("ix_analytics_events_created_at"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_user_id"), table_name="analytics_events")
    op.drop_table("analytics_events")

    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(op.f("ix_saved_notes_user_id"), table_name="saved_notes")
    op.drop_table("saved_notes")

    op.drop_index(op.f("ix_teacher_documents_created_at"), table_name="teacher_documents")
    op.drop_index(op.f("ix_teacher_documents_teacher_id"), table_name="teacher_documents")
    op.drop_table("teacher_documents")
