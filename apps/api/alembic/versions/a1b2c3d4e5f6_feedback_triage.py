"""feedback triage queue columns (S5.10)

Revision ID: a1b2c3d4e5f6
Revises: f9a0b1c2d3e4
Create Date: 2026-09-08

Three additive columns on the existing ``feedback`` table so the support
queue has somewhere to live (spec S5.10: "feedback triage queue (from
existing /feedback)"). No table is created and nothing is dropped, so the
migration is safe to apply in place and fully reversible:

* ``triaged``    -- has an admin looked at and dispositioned this item?
  Indexed because the queue read filters on it.
* ``triaged_at`` -- when it was dispositioned (NULL while open).
* ``triage_note``-- short staff-facing note. The privacy rules are unchanged:
  the column holds staff triage text written by admins, never exported by
  any user-facing route and never logged (R11).

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "feedback",
        sa.Column("triaged", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("feedback", sa.Column("triaged_at", sa.DateTime(), nullable=True))
    op.add_column("feedback", sa.Column("triage_note", sa.String(length=500), nullable=True))
    op.create_index(op.f("ix_feedback_triaged"), "feedback", ["triaged"])


def downgrade() -> None:
    op.drop_index(op.f("ix_feedback_triaged"), table_name="feedback")
    op.drop_column("feedback", "triage_note")
    op.drop_column("feedback", "triaged_at")
    op.drop_column("feedback", "triaged")
