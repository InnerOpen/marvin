"""add workspace_agents.tool_policy, icon, suggestions

Per-agent permission matrix: {category_id | tool_name: "allow" | "block"} overriding the defaults
derived from allow_writes. Additive nullable column — safe on Postgres and SQLite.

Revision ID: e6a2b3c4d5f7
Revises: d5f1a2b3c4e6
Create Date: 2026-09-13 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6a2b3c4d5f7"
down_revision: str | None = "d5f1a2b3c4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_agents") as batch:
        batch.add_column(sa.Column("tool_policy", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("icon", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("suggestions", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_agents") as batch:
        batch.drop_column("suggestions")
        batch.drop_column("icon")
        batch.drop_column("tool_policy")
