"""site rebuild requests: record what changed

Adds `changes` to site_rebuild_requests — the content changes a pending rebuild covers (newest last,
capped), so the rebuild's activity toast can list them. Additive and nullable — safe on Postgres and
SQLite; a row queued before this has no list and its rebuild still goes out.

Revision ID: c1e7a9d3f5b2
Revises: b8d2f6a1c9e3
Create Date: 2026-10-03 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1e7a9d3f5b2"
down_revision: str | None = "b8d2f6a1c9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("site_rebuild_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("changes", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("site_rebuild_requests", schema=None) as batch_op:
        batch_op.drop_column("changes")
