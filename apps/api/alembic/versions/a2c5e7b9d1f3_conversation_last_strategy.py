"""conversation last_strategy for adaptive re-teach (S1.5)

Revision ID: a2c5e7b9d1f3
Revises: f1a2b3c4d5e6
Create Date: 2026-09-06
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2c5e7b9d1f3"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("last_strategy", sa.String(length=24), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "last_strategy")
