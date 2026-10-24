"""social inbox: why a matched item wasn't answered

Adds ``held`` (JSON, nullable) to ``social_inbox_items``: when an auto-reply rule matched an item but the engine didn't answer
it — the person was answered by direct message within the rule's cool-down, or the network refused — the reason, the rule and
until when (services/integrations/social_inbox.hold). Cleared when a reply is recorded. Every existing item starts null.

Revision ID: b6d2f8a41c93
Revises: a8e3c51d7f42
Create Date: 2026-11-04 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6d2f8a41c93"
down_revision: str | None = "a8e3c51d7f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("held", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.drop_column("held")
