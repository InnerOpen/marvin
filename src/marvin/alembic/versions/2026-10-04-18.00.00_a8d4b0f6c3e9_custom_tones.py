"""ai settings: custom tones

Adds the workspace's own tones to workspace_ai_settings: `tones` (JSON — [{slug, name, instructions,
persona, description?}]) and `hidden_tones` (JSON — tone slugs left out of the pickers). Null → just the
built-ins, as before. Widens `workspace_agents.default_register` from String(16) to String(40) so an agent
can default to a custom tone's slug (Postgres enforces the length; SQLite doesn't).

Downgrade drops the columns and narrows the agent column back; any agent default longer than 16 chars
(only a custom tone's slug can be) is reset to null first, i.e. the workspace default.

Revision ID: a8d4b0f6c3e9
Revises: f7c3a9e5b2d8
Create Date: 2026-10-04 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8d4b0f6c3e9"
down_revision: str | None = "f7c3a9e5b2d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_LENGTH = 16
NEW_LENGTH = 40


def upgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tones", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("hidden_tones", sa.JSON(), nullable=True))
    with op.batch_alter_table("workspace_agents", schema=None) as batch_op:
        batch_op.alter_column(
            "default_register",
            existing_type=sa.String(length=OLD_LENGTH),
            type_=sa.String(length=NEW_LENGTH),
            existing_nullable=True,
        )


def downgrade() -> None:
    agents = sa.table("workspace_agents", sa.column("default_register", sa.String()))
    op.execute(agents.update().where(sa.func.length(agents.c.default_register) > OLD_LENGTH).values(default_register=None))
    with op.batch_alter_table("workspace_agents", schema=None) as batch_op:
        batch_op.alter_column(
            "default_register",
            existing_type=sa.String(length=NEW_LENGTH),
            type_=sa.String(length=OLD_LENGTH),
            existing_nullable=True,
        )
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.drop_column("hidden_tones")
        batch_op.drop_column("tones")
