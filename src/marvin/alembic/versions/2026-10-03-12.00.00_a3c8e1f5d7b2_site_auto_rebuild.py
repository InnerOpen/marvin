"""preferences: site auto rebuild

Adds `site_auto_rebuild` (default true) to group_preferences: request a coalesced static-site rebuild
whenever published content changes. Additive — safe on Postgres and SQLite.

Revision ID: a3c8e1f5d7b2
Revises: f2b7d9e4a1c6
Create Date: 2026-10-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c8e1f5d7b2"
down_revision: str | None = "f2b7d9e4a1c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("site_auto_rebuild", sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("site_auto_rebuild")
