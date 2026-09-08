"""security: audit_log table + encrypted guardian phone column (S5.6)

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-09-06

Two additive changes for S5.6 security hardening:

* ``audit_log`` -- append-only trail for the five sensitive admin/support
  events (role_change, data_export, purge, qp_finalize, impersonation).
  It stores ids and non-content metadata only, never message text.
* ``parents.phone_enc`` -- the guardian phone moves here as ciphertext
  (Fernet, prefix ``fernet:``) when PII_ENC_KEY is configured. Existing
  ``parents.phone`` values are left untouched by this migration: the app
  reads/writes phone_enc going forward and a plain value in phone is
  treated as legacy data (no rows carry one today -- the column was never
  written by the app).

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: str | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_role", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("target", sa.String(length=120), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_audit_log_actor_user_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])
    op.create_index(op.f("ix_audit_log_actor_user_id"), "audit_log", ["actor_user_id"])
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"])
    op.add_column("parents", sa.Column("phone_enc", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("parents", "phone_enc")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_actor_user_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_created_at"), table_name="audit_log")
    op.drop_table("audit_log")
