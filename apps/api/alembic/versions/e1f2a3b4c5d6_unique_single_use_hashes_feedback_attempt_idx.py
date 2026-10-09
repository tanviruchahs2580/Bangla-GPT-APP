"""DAT-002: reconcile ORM/migration drift surfaced by ``alembic check``.

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
Create Date: 2026-10-09

``alembic check`` had never been run in CI, so the models and the migrations
were allowed to diverge. Wiring it in (commit c56266f) exposed four
differences; this migration closes all of them.

  On every dialect:
    1. ``ix_email_verifications_token_hash`` was created non-unique by
       d4e5f6a7b8c9, but ``EmailVerification.token_hash`` is ``unique=True``.
    2. ``ix_parent_invites_code_hash`` had the same defect against
       ``ParentInvite.code_hash``.
    3. ``Feedback.attempt_id`` is declared ``index=True`` but no index was
       ever created for it.

  On dialects that persist column comments (Postgres; not SQLite):
    4. ``ClassTeacher.subject`` carries ``comment="'' means all subjects"``
       in the ORM, which the table's creation migration never applied.

A single-use code is redeemed by looking the row up by its hash, so the hash
must be unique or a collision could make one code unredeemable and make "the
row for this hash" ambiguous. Both hash columns hold SHA-256 hex digests of
high-entropy random tokens, so duplicates cannot occur in practice; the
upgrade still refuses to run if they somehow exist rather than emitting a
confusing CREATE UNIQUE INDEX error mid-build (and, on Postgres, aborting the
surrounding transaction).

The comment step is a no-op on SQLite: the dialect does not support comments,
does not store them, and ``alembic check`` does not compare them there, so
guarding on ``supports_comments`` keeps the two dialects in agreement.

Fully reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column) pairs that are about to gain a UNIQUE constraint.
_SINGLE_USE_INDEXES = (
    ("email_verifications", "token_hash"),
    ("parent_invites", "code_hash"),
)

_SUBJECT_COMMENT_TABLE = "class_teachers"
_SUBJECT_COMMENT_COLUMN = "subject"
_SUBJECT_COMMENT = "'' means all subjects"


def _assert_no_duplicates(table: str, column: str) -> None:
    """Fail loudly if tightening this column to UNIQUE would be impossible."""
    duplicate = op.get_bind().execute(
        sa.text(
            f"SELECT {column} FROM {table} GROUP BY {column} HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            f"Cannot make {table}.{column} unique: duplicate values exist "
            f"(first: {duplicate[0]!r}). Deduplicate before applying this migration."
        )


def _dialect_supports_comments() -> bool:
    return bool(op.get_bind().dialect.supports_comments)


def upgrade() -> None:
    for table, column in _SINGLE_USE_INDEXES:
        _assert_no_duplicates(table, column)
        index = f"ix_{table}_{column}"
        op.drop_index(index, table_name=table)
        op.create_index(index, table, [column], unique=True)

    op.create_index("ix_feedback_attempt_id", "feedback", ["attempt_id"])

    if _dialect_supports_comments():
        op.alter_column(
            _SUBJECT_COMMENT_TABLE,
            _SUBJECT_COMMENT_COLUMN,
            existing_type=sa.String(length=60),
            existing_nullable=False,
            comment=_SUBJECT_COMMENT,
        )


def downgrade() -> None:
    if _dialect_supports_comments():
        op.alter_column(
            _SUBJECT_COMMENT_TABLE,
            _SUBJECT_COMMENT_COLUMN,
            existing_type=sa.String(length=60),
            existing_nullable=False,
            comment=None,
        )

    op.drop_index("ix_feedback_attempt_id", table_name="feedback")

    for table, column in _SINGLE_USE_INDEXES:
        index = f"ix_{table}_{column}"
        op.drop_index(index, table_name=table)
        op.create_index(index, table, [column], unique=False)
