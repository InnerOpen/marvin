"""system playbooks: a workspace's own switches

Adds nullable ``system_playbooks_off`` (JSON, a list of Playbook names) to ``workspace_ai_settings``: the system
Playbooks (shipped by Marvin and its plugins, read from the installed packages, no rows) this workspace switched off.
Null or empty means all of them are on. Names are kept even when a plugin is uninstalled, so a switch survives a
reinstall.

No backfill. Downgrade drops the column.

Revision ID: b5e9c3a72d18
Revises: a4d8e1c27b63
Create Date: 2026-10-29 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e9c3a72d18"
down_revision: str | None = "a4d8e1c27b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("system_playbooks_off", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_ai_settings", schema=None) as batch_op:
        batch_op.drop_column("system_playbooks_off")
