"""BGPT-SEC-001 follow-up: widen users.totp_secret for ciphertext

Revision ID: b6c8d0e2f4a6
Revises: a5b7c9d1e3f7
Create Date: 2026-11-14

The original column is varchar(64) — sized for a raw base32 seed (32 chars).
The encrypted form (``totp1:`` + Fernet token) is ~150+ characters, which
PostgreSQL enforces (StringDataRightTruncation) and SQLite does not — the
CI Postgres parity leg caught what local SQLite could not. Widen to 255.

Additive and reversible (restore the 64-char width on downgrade; no row
can carry a value that would truncate because the app only writes
ciphertext when the widened column exists — on downgrade the sweep is
inert because the release that runs it also runs upgrade).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6c8d0e2f4a6"
down_revision: str | Sequence[str] | None = "a5b7c9d1e3f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "totp_secret",
            existing_type=sa.String(length=64),
            type_=sa.String(length=255),
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "totp_secret",
            existing_type=sa.String(length=255),
            type_=sa.String(length=64),
        )
