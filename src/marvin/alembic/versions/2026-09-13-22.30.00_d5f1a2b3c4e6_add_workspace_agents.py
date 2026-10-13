"""add workspace_agents table

User-definable AI agents per workspace (kind persona | model, system prompt, model override, tool
allowlist, write policy, who may talk to it). The system agents (marvin/ask/chat) are code, not rows.
Additive CREATE TABLE — safe on Postgres and SQLite.

Revision ID: d5f1a2b3c4e6
Revises: c4e8b19d7a52
Create Date: 2026-09-13 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "d5f1a2b3c4e6"
down_revision: str | None = "c4e8b19d7a52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_agents",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("kind", sa.String(length=16), server_default="persona", nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("model_override", sa.String(length=120), nullable=True),
        sa.Column("tool_allowlist", sa.JSON(), nullable=True),
        sa.Column("default_register", sa.String(length=16), nullable=True),
        sa.Column("min_role", sa.Integer(), server_default="1", nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("allow_writes", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_by", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "slug", name="uq_workspace_agents_group_slug"),
    )
    op.create_index("ix_workspace_agents_group_id", "workspace_agents", ["group_id"])
    op.create_index("ix_workspace_agents_slug", "workspace_agents", ["slug"])


def downgrade() -> None:
    op.drop_index("ix_workspace_agents_slug", table_name="workspace_agents")
    op.drop_index("ix_workspace_agents_group_id", table_name="workspace_agents")
    op.drop_table("workspace_agents")
