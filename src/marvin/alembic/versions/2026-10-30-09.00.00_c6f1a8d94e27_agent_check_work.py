"""agents: check their work

Adds ``check_work`` (boolean, not null, default false) to ``workspace_agents``: an agent that checks its work before it
finishes (services/ai/work_check.py). Every existing agent keeps today's behaviour (false).

No backfill beyond the default. Downgrade drops the column.

Revision ID: c6f1a8d94e27
Revises: b5e9c3a72d18
Create Date: 2026-10-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6f1a8d94e27"
down_revision: str | None = "b5e9c3a72d18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("check_work", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("workspace_agents", schema=None) as batch_op:
        batch_op.drop_column("check_work")
