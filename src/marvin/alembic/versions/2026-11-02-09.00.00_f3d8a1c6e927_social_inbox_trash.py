"""social inbox: trash

Adds ``trashed_at`` (nullable, timezone-aware) to ``social_inbox_items``: an item a person moved to the inbox's Trash — out of
the inbox, never answered by a rule, restorable (services/integrations/social_inbox.py). Nothing on the network changes. The
item keeps its status, so restoring it brings back what it was. Every existing row keeps null (in the inbox).

Revision ID: f3d8a1c6e927
Revises: e2c7f4a9b815
Create Date: 2026-11-02 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3d8a1c6e927"
down_revision: str | None = "e2c7f4a9b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.drop_column("trashed_at")
