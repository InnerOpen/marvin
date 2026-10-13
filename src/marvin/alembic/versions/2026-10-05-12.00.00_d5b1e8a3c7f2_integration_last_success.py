"""integrations: last successful action

Adds ``integrations.last_success_at``: when a provider action through this connection last succeeded
(a workflow step, an event subscription, a capability call or a scheduled task). The Alerts & health
page shows it next to the last health check. Null until the next success.

Additive — safe on Postgres and SQLite.

Revision ID: d5b1e8a3c7f2
Revises: c9e2f4a6b8d1
Create Date: 2026-10-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5b1e8a3c7f2"
down_revision: str | None = "c9e2f4a6b8d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("integrations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("integrations", schema=None) as batch_op:
        batch_op.drop_column("last_success_at")
