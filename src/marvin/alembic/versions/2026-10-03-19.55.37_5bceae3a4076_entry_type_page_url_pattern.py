"""entry type page url pattern

Adds `entry_types.page_url_pattern` (nullable string), e.g. `/works/{slug}` — where the workspace's
site renders an entry of that type, so Marvin can build an entry's public URL (with the workspace's
Canonical URL). Null → no URL, today's behaviour. Additive — safe on Postgres and SQLite.

Revision ID: 5bceae3a4076
Revises: c4e7a2d9f1b6
Create Date: 2026-10-03 19:55:37.363665

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5bceae3a4076"
down_revision: str | None = "c4e7a2d9f1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("entry_types", schema=None) as batch_op:
        batch_op.add_column(sa.Column("page_url_pattern", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("entry_types", schema=None) as batch_op:
        batch_op.drop_column("page_url_pattern")
