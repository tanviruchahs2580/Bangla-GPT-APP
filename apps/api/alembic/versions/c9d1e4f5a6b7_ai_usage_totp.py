"""AI-002 usage ledger + AUTH-001 TOTP column.

Revision ID: c9d1e4f5a6b7
Revises: b7e3f5a8c2d4
Create Date: 2026-09-11

Two additive, fully reversible changes:

* ``ai_usage`` ledger table (AI-002): one row per generation that reached a
  provider — user, route, model, token estimates, estimated USD cost.
  Indexed (user_id, created_at) for the monthly budget SUM. Cleaned by
  DELETE /users/me (BUG-4 rule, enforced in routers/users.py).
* ``users.totp_secret`` nullable column (AUTH-001): base32 TOTP secret.
  NULL = MFA disabled. Secrets are stored only after possession is proven
  (verify step), never at enroll.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d1e4f5a6b7"
down_revision: str | None = "b7e3f5a8c2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("route", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_usage_user_id"), "ai_usage", ["user_id"])
    op.create_index(op.f("ix_ai_usage_created_at"), "ai_usage", ["created_at"])
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_secret")
    op.drop_index(op.f("ix_ai_usage_created_at"), table_name="ai_usage")
    op.drop_index(op.f("ix_ai_usage_user_id"), table_name="ai_usage")
    op.drop_table("ai_usage")
