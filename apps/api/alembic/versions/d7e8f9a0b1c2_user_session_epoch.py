"""F-05: user token-epoch column for session revocation on rotation.

Revision ID: d7e8f9a0b1c2
Revises: c9d1e4f5a6b7
Create Date: 2026-10-06

``users.sessions_invalidated_at`` is the token epoch: when a password
change/reset sets it, every access token whose ``iat`` is <= that moment is
refused by ``get_current_user``. Existing sessions can no longer ride out a
credential rotation. Nullable; NULL (the default for all existing rows)
means "no rotation has happened" and accepts tokens as before — the
migration is purely additive and fully reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c9d1e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("sessions_invalidated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("sessions_invalidated_at")
