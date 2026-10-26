"""the Social Battery: a mood meter per person and agent, and the workspace switch

Creates ``ai_mood_meters`` (one row per workspace, person and agent: ``level`` 0–100 from 50, ``band_since``, ``state``,
``last_seen_at``, ``reset_at``) and adds ``mood_enabled`` (boolean, not null, default false) to ``workspace_ai_settings``:
the meter runs only where a workspace switched it on (services/ai/mood.py). Every workspace starts off.

Revision ID: e4a9c7d2b5f1
Revises: d8f2b6c4e1a7
Create Date: 2026-11-07 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "e4a9c7d2b5f1"
down_revision: str | None = "d8f2b6c4e1a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_mood_meters",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("user_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("agent_slug", sa.String(length=64), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("band_since", sa.JSON(), nullable=True),
        sa.Column("state", sa.JSON(), nullable=True),
        sa.Column("last_seen_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("reset_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "user_id", "agent_slug", name="uq_ai_mood_meters_person_agent"),
    )
    op.create_index("ix_ai_mood_meters_created_at", "ai_mood_meters", ["created_at"])
    op.create_index("ix_ai_mood_meters_group_id", "ai_mood_meters", ["group_id"])
    op.create_index("ix_ai_mood_meters_user_id", "ai_mood_meters", ["user_id"])
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mood_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.drop_column("mood_enabled")
    op.drop_index("ix_ai_mood_meters_user_id", table_name="ai_mood_meters")
    op.drop_index("ix_ai_mood_meters_group_id", table_name="ai_mood_meters")
    op.drop_index("ix_ai_mood_meters_created_at", table_name="ai_mood_meters")
    op.drop_table("ai_mood_meters")
