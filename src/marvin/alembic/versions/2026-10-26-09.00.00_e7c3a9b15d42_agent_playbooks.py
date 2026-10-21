"""add workspace_agents.playbooks

Per-agent Playbook settings: {"names": [...] | None, "always": [...]}. None = every published Playbook and none loaded up
front. Additive nullable column: safe on Postgres and SQLite.

Revision ID: e7c3a9b15d42
Revises: d3b9f27a6c14
Create Date: 2026-10-26 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7c3a9b15d42"
down_revision: str | None = "d3b9f27a6c14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_agents") as batch:
        batch.add_column(sa.Column("playbooks", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_agents") as batch:
        batch.drop_column("playbooks")
