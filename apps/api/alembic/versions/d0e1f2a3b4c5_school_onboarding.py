"""school onboarding: users.school_id + single-use school invite codes

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-06

S3.1: staff accounts join a school via one-time invite codes; school_admin is
a new role VALUE (the column is a plain string, so no CHECK constraint had to
change -- 'role migration green' is proven by value round-trip tests).
Existing users keep school_id NULL and continue via the default school.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch mode: SQLite cannot ALTER constraints (copy-and-move recreate).
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("school_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_school_id", "schools", ["school_id"], ["id"]
        )
    op.create_index(op.f("ix_users_school_id"), "users", ["school_id"], unique=False)
    op.create_table(
        "school_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("school_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("used_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_school_invites_code_hash"), "school_invites", ["code_hash"], unique=True
    )
    op.create_index(
        op.f("ix_school_invites_school_id"), "school_invites", ["school_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_school_invites_school_id"), table_name="school_invites")
    op.drop_index(op.f("ix_school_invites_code_hash"), table_name="school_invites")
    op.drop_table("school_invites")
    op.drop_index(op.f("ix_users_school_id"), table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_school_id", type_="foreignkey")
        batch_op.drop_column("school_id")
