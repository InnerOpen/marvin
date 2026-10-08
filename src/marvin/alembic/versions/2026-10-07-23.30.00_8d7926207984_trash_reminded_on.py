"""trash reminded on: the daily "Trash emptying soon" reminder

Schema (additive):
  - ``group_preferences.trash_reminded_on`` — the last day (UTC) the workspace was reminded that its Trash's
    auto-empty will delete items forever within a day; at most one reminder a day. Null: never reminded.

Revision ID: 8d7926207984
Revises: 91b1c4963014
Create Date: 2026-10-07 23:30:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8d7926207984"
down_revision: str | None = "91b1c4963014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trash_reminded_on", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("trash_reminded_on")
