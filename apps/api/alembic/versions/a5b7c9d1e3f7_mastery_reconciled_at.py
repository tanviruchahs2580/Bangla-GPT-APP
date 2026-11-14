"""BGPT-DATA-001: concept_mastery.reconciled_at stamp

Revision ID: a5b7c9d1e3f7
Revises: dbf1d2e3f4a5
Create Date: 2026-11-14

The nightly mastery reconciliation becomes monotone (heal-up, never shrink)
so the 730-day answer-log retention purge can no longer erase lifetime
learning aggregates. This migration adds the last-reconciled stamp the
report requires: NULL means the row has not yet been examined by the new
reconciliation. No data is written or rewritten here — the first nightly
pass stamps rows as it examines them.

Additive and reversible (drop column); SQLite is handled by batch mode.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5b7c9d1e3f7"
down_revision: str | Sequence[str] | None = "dbf1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("concept_mastery") as batch:
        batch.add_column(sa.Column("reconciled_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("concept_mastery") as batch:
        batch.drop_column("reconciled_at")
