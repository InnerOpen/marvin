"""ai settings: assistant icon

Adds `assistant_icon` to workspace_ai_settings — the Ask Marvin bubble's icon, an emoji or an image
URL. Null → the default 🤖. Additive — safe on Postgres and SQLite.

Revision ID: f2b7d9e4a1c6
Revises: e6a1c4d8b3f7
Create Date: 2026-10-02 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b7d9e4a1c6"
down_revision: str | None = "e6a1c4d8b3f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("assistant_icon", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.drop_column("assistant_icon")
