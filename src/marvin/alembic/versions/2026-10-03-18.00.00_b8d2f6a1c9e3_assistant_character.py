"""ai settings: assistant character

Adds `assistant_character` (JSON) to workspace_ai_settings — the Ask Marvin bubble's animated
character, one animation per bubble state, shown instead of the icon. Null → the icon. Additive — safe
on Postgres and SQLite.

Revision ID: b8d2f6a1c9e3
Revises: a3c8e1f5d7b2
Create Date: 2026-10-03 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d2f6a1c9e3"
down_revision: str | None = "a3c8e1f5d7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("assistant_character", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.drop_column("assistant_character")
