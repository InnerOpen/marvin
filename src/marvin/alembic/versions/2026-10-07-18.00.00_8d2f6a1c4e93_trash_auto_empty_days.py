"""preferences: trash auto-empty days

Adds `trash_auto_empty_days` to group_preferences: the workspace's override of how long an entry stays in
the Trash before it is deleted forever (0 = never). Null — every existing workspace — inherits the platform
default (platform_settings key `trash`, 30 days unless a super admin changes it). Additive — safe on
Postgres and SQLite.

Revision ID: 8d2f6a1c4e93
Revises: efee4271020c
Create Date: 2026-10-07 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d2f6a1c4e93"
down_revision: str | None = "efee4271020c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trash_auto_empty_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("trash_auto_empty_days")
