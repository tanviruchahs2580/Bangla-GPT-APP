"""AUD-0046: bound school invite codes to a lifetime.

Revision ID: f2b3c4d5e6f7
Revises: e1f2a3b4c5d6
Create Date: 2026-10-09

``SchoolInvite`` had no ``expires_at`` column: staff invite codes were
single-use but never time-limited, so a leaked code stayed redeemable forever.
This migration adds the nullable column; creation now stamps
``now + invite_ttl_minutes`` (default 24h) and the join-school claim enforces
it.

Backfill policy for the rows that pre-date this migration (all have NULL
``expires_at``) is deliberately NOT decided here - audit finding AUD-0046 rates
that a Class D (needs-human) decision: either "expire all unused codes" or
"grandfather them with a grace TTL". The code path fails closed meanwhile:
a NULL ``expires_at`` evaluates NULL against ``>= now`` in ``claim_single_use``
and the claim is refused, so outstanding pre-fix codes are already unusable
until an operator backfills them. That outcome (expiring all unused codes) is
the conservative-security default; the human decision and the backfill SQL live
in ``HUMAN_ACTIONS.md``.

Fully reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b3c4d5e6f7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "school_invites",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("school_invites", "expires_at")
