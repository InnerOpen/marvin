"""social inbox: what an item carried

Adds ``attachments`` (nullable JSON) to ``social_inbox_items``: a list of ``{type, url, title}`` an item arrived with — a
direct message's picture, a shared post and its caption (services/integrations/social_inbox.py). Items a network pushes by
webhook bring the new kinds (message, story_reply, story_mention, reaction, live_comment); ``kind`` is a plain string, so
they need no change of their own. Every existing row keeps null.

Revision ID: e2c7f4a9b815
Revises: d7a2b9e4f310
Create Date: 2026-11-01 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c7f4a9b815"
down_revision: str | None = "d7a2b9e4f310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("attachments", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.drop_column("attachments")
