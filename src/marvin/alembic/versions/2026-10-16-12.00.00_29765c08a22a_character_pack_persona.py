"""character pack persona: a library pack carries its persona; an agent gets one of its own

Adds `character_packs.persona` (JSON: assistant_name, persona_prompt, bubble_lines, default_register, icon,
mood), copied into a workspace or agent when it picks the pack. `workspace_agents` gains `persona_prompt`
(Text), `bubble_lines` (JSON) and `bubble_lines_source` (String), so an agent speaks and bubbles as its
own character, and `mood` (JSON) — the Social Battery settings, stored but read by nothing yet — which
`workspace_ai_settings` gains too. Null everywhere → as before. Additive — safe on Postgres and SQLite.

Revision ID: 29765c08a22a
Revises: 4166a87cee01
Create Date: 2026-10-16 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29765c08a22a"
down_revision: str | None = "4166a87cee01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("character_packs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("persona", sa.JSON(), nullable=True))

    with op.batch_alter_table("workspace_agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("persona_prompt", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("bubble_lines", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("bubble_lines_source", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("mood", sa.JSON(), nullable=True))

    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mood", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.drop_column("mood")

    with op.batch_alter_table("workspace_agents", schema=None) as batch_op:
        batch_op.drop_column("mood")
        batch_op.drop_column("bubble_lines_source")
        batch_op.drop_column("bubble_lines")
        batch_op.drop_column("persona_prompt")

    with op.batch_alter_table("character_packs", schema=None) as batch_op:
        batch_op.drop_column("persona")
