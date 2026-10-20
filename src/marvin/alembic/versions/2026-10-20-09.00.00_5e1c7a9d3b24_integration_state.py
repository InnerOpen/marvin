"""integrations: state

Marvin's own bookkeeping for a connection, as `integrations.state` (JSON, nullable): the social engagement engine keeps
each integration's comment-read cursors and its retry queue there (services/integrations/social_engagement.py). Null
means nothing is kept yet. Downgrade drops it (the engine then reads from the newest comments again; its dedupe is the
reply log, not this).

Revision ID: 5e1c7a9d3b24
Revises: 64b760a74bb8
Create Date: 2026-10-20 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e1c7a9d3b24"
down_revision: str | None = "64b760a74bb8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("integrations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("integrations", schema=None) as batch_op:
        batch_op.drop_column("state")
