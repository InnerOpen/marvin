"""social inbox: the entry an item was saved as (Save as idea)

Adds ``idea_entry_id`` (nullable, a foreign key to ``entries.id``, ``ON DELETE SET NULL``) to ``social_inbox_items``: the
draft entry a person made from the item (services/integrations/social_inbox_actions.save_idea). Every existing item starts empty.

Revision ID: d8f2b6c4e1a7
Revises: c3a7e1d95b28
Create Date: 2026-11-06 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "d8f2b6c4e1a7"
down_revision: str | None = "c3a7e1d95b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "fk_social_inbox_items_idea_entry_id_entries"


def upgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("idea_entry_id", marvin.db.migration_types.GUID(), nullable=True))
        batch_op.create_foreign_key(FK, "entries", ["idea_entry_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.drop_constraint(FK, type_="foreignkey")
        batch_op.drop_column("idea_entry_id")
