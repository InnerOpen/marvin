"""ai settings: bubble lines

Adds the Ask bubble's canned lines in the workspace's own voice to workspace_ai_settings:
`bubble_lines` (JSON — {greetings, taglines, thinking, errors, emotes}), `bubble_lines_source`
("generated" | "edited"), `bubble_lines_updated_at` and `bubble_lines_warning` (why the last
generation failed). Null → the bubble's built-in lines. Additive — safe on Postgres and SQLite.

Revision ID: e6b2d8f4a1c7
Revises: d5a9c3e7b1f4
Create Date: 2026-10-03 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6b2d8f4a1c7"
down_revision: str | None = "d5a9c3e7b1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bubble_lines", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("bubble_lines_source", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("bubble_lines_updated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("bubble_lines_warning", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.drop_column("bubble_lines_warning")
        batch_op.drop_column("bubble_lines_updated_at")
        batch_op.drop_column("bubble_lines_source")
        batch_op.drop_column("bubble_lines")
