"""group preferences: email branding

A workspace's own name, footer line and accent colour for the emails it sends (Settings → Email → Branding), as
`group_preferences.email_branding_json`. Null means every value falls back: the name to the site title or workspace
name, the footer to "Sent by <name>", the colour to the platform's (services/email/branding.py). Downgrade drops it.

Revision ID: 64b760a74bb8
Revises: 6d4b5730ec18
Create Date: 2026-10-19 21:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "64b760a74bb8"
down_revision: str | None = "6d4b5730ec18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email_branding_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("email_branding_json")
