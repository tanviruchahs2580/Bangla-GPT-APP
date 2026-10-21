"""H-14: store every timestamp as timestamptz (UTC storage)

Revision ID: b5d7f9a1c3e5
Revises: a3c5e7f9b1d3
Create Date: 2026-10-19

Every timestamp column was ``timestamp without time zone``: the stored
instant was only correct while the *reader* assumed UTC, and the reading
session was pinned to UTC by ``db/session.py`` (AUD-HI-02 shipped the pin).
This revision upgrades the storage itself to ``timestamptz`` (UTC), so a
``psql`` session, a BI tool, a dump restored on another host and a native
``now()`` comparison all read the same instant.

``USING <col> AT TIME ZONE 'UTC'`` is correct because the writing session
has been pinned to UTC since AUD-HI-02; the values already denote UTC wall
clock readings. The inverse expression restores the previous shape on
downgrade, so the cycle is lossless while that pin is in force.

PostgreSQL rewrites each table under ACCESS EXCLUSIVE; run it in the deploy
window (``docs/operations/TIMEZONE.md`` documents the rollout and rollback).
SQLite has no timestamp type -- its columns are ISO-8601 text whose type
name has no semantics -- so both directions are deliberate no-ops there.

The Python-facing contract is unchanged: ``db/types.UtcDateTime`` receives
aware values for PostgreSQL and returns naive UTC, which is what the ~30
existing ``.replace(tzinfo=None)`` call sites expect. The router-side
aware-flow cleanup stays a separate, independent change (AUD-EF-16).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5d7f9a1c3e5"
down_revision: str | Sequence[str] | None = "a3c5e7f9b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: table -> timestamp columns converted by the upgrade.
_TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "ai_jobs": (
        "created_at",
        "updated_at",
    ),
    "ai_usage": ("created_at",),
    "analytics_events": ("created_at",),
    "assignments": (
        "due_at",
        "created_at",
    ),
    "audit_log": ("created_at",),
    "chapter_contents": ("created_at",),
    "chapter_progress": ("updated_at",),
    "chat_messages": ("created_at",),
    "class_students": ("created_at",),
    "class_teachers": ("created_at",),
    "classrooms": ("created_at",),
    "concept_mastery": ("updated_at",),
    "concepts": ("created_at",),
    "conversations": ("created_at",),
    "email_verifications": (
        "expires_at",
        "used_at",
        "created_at",
    ),
    "feedback": (
        "triaged_at",
        "created_at",
    ),
    "job_runs": (
        "started_at",
        "finished_at",
    ),
    "notifications": (
        "read_at",
        "created_at",
    ),
    "parent_invites": (
        "expires_at",
        "used_at",
        "created_at",
    ),
    "parent_student_links": ("created_at",),
    "parents": ("created_at",),
    "password_resets": (
        "expires_at",
        "used_at",
        "created_at",
    ),
    "practice_items": ("updated_at",),
    "question_bank": ("created_at",),
    "question_papers": (
        "reviewed_at",
        "finalized_at",
        "created_at",
    ),
    "quiz_attempts": ("created_at",),
    "revision_queue": ("updated_at",),
    "saved_notes": ("created_at",),
    "school_invites": (
        "created_at",
        "used_at",
        "expires_at",
    ),
    "schools": ("created_at",),
    "short_tests": ("created_at",),
    "student_abilities": ("updated_at",),
    "student_invites": (
        "expires_at",
        "used_at",
        "created_at",
    ),
    "students": (
        "consent_at",
        "created_at",
    ),
    "support_plans": ("created_at",),
    "teacher_documents": ("created_at",),
    "teachers": ("created_at",),
    "users": (
        "sessions_invalidated_at",
        "locked_until",
        "created_at",
    ),
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite: text timestamps whose type name has no semantics
    for table, columns in _TIMESTAMP_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                type_=sa.DateTime(timezone=True),
                postgresql_using=f"{column} AT TIME ZONE 'UTC'",
            )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # symmetric no-op; see the module docstring
    for table, columns in _TIMESTAMP_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                type_=sa.DateTime(timezone=False),
                postgresql_using=f"{column} AT TIME ZONE 'UTC'",
            )
