"""F-175/DB-02: drop the single-column indexes the composites already serve

Revision ID: e4b8c0d2f6a8
Revises: d2f6a8c0b4e1
Create Date: 2026-10-30

Two redundant single-column indexes, the pattern migration a3c5e7f9b1d3
pruned from eleven other tables (it skipped these because both arrived later):

* ``ix_ai_usage_user_id`` predates the composite
  ``ix_ai_usage_user_created`` (``user_id, created_at``) added by
  b5d7e9f1a3c7 for the budget-gate hot path. A single-column index on the
  composite's leading column is a strict prefix of it, so the planner can
  always use the composite instead and the single-column b-tree is a second
  write on every insert. ai_usage is the write-hot spend ledger.

* ``ix_ai_jobs_user_id`` is a strict prefix of the unique
  ``uq_ai_jobs_idempotency`` (``user_id, kind, idempotency_key``) added by
  d2f6a8c0b4e1; a user_id lookup is served by that index on both engines.

Two DROP INDEX / CREATE INDEX pairs, supported by both engines without a table
rebuild. Reversible: the downgrade recreates both under the same names.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4b8c0d2f6a8"
down_revision: str | Sequence[str] | None = "d2f6a8c0b4e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (index name, table, column) dropped by the upgrade, recreated on downgrade.
_PRUNED_INDEXES = (
    ("ix_ai_usage_user_id", "ai_usage", "user_id"),
    ("ix_ai_jobs_user_id", "ai_jobs", "user_id"),
)


def upgrade() -> None:
    for index_name, table, _column in _PRUNED_INDEXES:
        op.drop_index(index_name, table_name=table)


def downgrade() -> None:
    for index_name, table, column in _PRUNED_INDEXES:
        op.create_index(index_name, table, [column])
