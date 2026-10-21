"""H-11: per-guardian digest preference and the email-bounce ledger

Revision ID: c6e8a0b2d4f6
Revises: b5d7f9a1c3e5
Create Date: 2026-10-19

Two gaps the audit found in the email surface:

* ``parents.digest_opt_out`` / ``parents.digest_language`` -- a user-level
  preference (the weekly digest was controlled only by the server-wide
  ``PARENT_DIGEST_ENABLED``), honoured by ``services/parent_digest.py``;
* ``email_bounces`` -- the suppression ledger a bounce/complaint path writes
  to. Only the SHA-256 of the lowercased recipient is stored.

Existing guardian rows take the server defaults (digest on, Bengali), so the
change is additive and reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6e8a0b2d4f6"
down_revision: str | Sequence[str] | None = "b5d7f9a1c3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Additive: defaults keep every existing guardian subscribed in bn."""
    with op.batch_alter_table("parents") as batch:
        batch.add_column(
            sa.Column("digest_opt_out", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("digest_language", sa.String(length=2), nullable=False, server_default="bn")
        )
    op.create_table(
        "email_bounces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("bounce_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_bounced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_bounced_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("bounce_count >= 1", name="ck_email_bounces_count"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipient_hash", name="uq_email_bounces_recipient_hash"),
    )


def downgrade() -> None:
    op.drop_table("email_bounces")
    with op.batch_alter_table("parents") as batch:
        batch.drop_column("digest_language")
        batch.drop_column("digest_opt_out")
