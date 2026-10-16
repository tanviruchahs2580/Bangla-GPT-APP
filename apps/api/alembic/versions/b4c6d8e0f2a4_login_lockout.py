"""S-002: per-account failed-login lockout columns on ``users``.

Revision ID: b4c6d8e0f2a4
Revises: f2b3c4d5e6f7
Create Date: 2026-10-16

The only anti-automation control on ``POST /auth/login`` was the per-IP rule
(10/min), so with IP rotation (or after S-001 is fixed by trusting the
proxy) any number of password guesses against one known account was possible.

Two additive, nullable/defaulted columns:

* ``failed_login_count`` — consecutive password failures, NOT NULL with a
  server default of 0 so the ALTER can backfill existing rows. Reset to 0 by
  any successful sign-in (in ``routers/auth.py``).
* ``locked_until`` — naive UTC timestamp the account stays locked until;
  NULL when the account is not locked. Stamped with a progressive delay
  (60 s doubling per failure past the threshold, capped at 1 h) once the
  counter crosses the threshold.

Fully reversible: the downgrade drops both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c6d8e0f2a4"
down_revision: str | None = "f2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
