"""character library: platform bubble-character packs, and a character per agent

Adds `character_packs` — packs a platform admin uploads once for any workspace or agent to pick — and
`workspace_agents.character` (JSON), the bubble's character while that agent talks. Null → the
workspace's character. Additive — safe on Postgres and SQLite.

Revision ID: c4e7a2d9f1b6
Revises: c1e7a9d3f5b2
Create Date: 2026-10-03 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "c4e7a2d9f1b6"
down_revision: str | None = "c1e7a9d3f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "character_packs",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("pack", sa.JSON(), nullable=False),
        sa.Column("created_by", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("character_packs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_character_packs_slug"), ["slug"], unique=True)
        batch_op.create_index(batch_op.f("ix_character_packs_created_at"), ["created_at"], unique=False)

    with op.batch_alter_table("workspace_agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("character", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_agents", schema=None) as batch_op:
        batch_op.drop_column("character")

    with op.batch_alter_table("character_packs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_character_packs_created_at"))
        batch_op.drop_index(batch_op.f("ix_character_packs_slug"))
    op.drop_table("character_packs")
