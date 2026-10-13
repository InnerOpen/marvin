"""add workspace_ai_settings.agent_tool_policies

A workspace's overrides of the built-in agents' permission matrices: {agent_slug: {category_id |
tool_name: "allow" | "ask" | "block"}}. Built-in agents are code, not rows, so their per-workspace
matrix lives on the workspace's AI settings row. Additive nullable column — safe on Postgres and SQLite.

Revision ID: 7cb7b06de5e6
Revises: 011f6c720d1d
Create Date: 2026-10-06 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7cb7b06de5e6"
down_revision: str | None = "011f6c720d1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings") as batch:
        batch.add_column(sa.Column("agent_tool_policies", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings") as batch:
        batch.drop_column("agent_tool_policies")
