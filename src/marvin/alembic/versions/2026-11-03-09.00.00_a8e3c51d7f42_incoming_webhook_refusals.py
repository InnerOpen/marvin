"""incoming webhooks: the last refused delivery

Adds ``refused_count`` (integer, not null, default 0), ``last_refused_at`` and ``last_refused_reason`` (nullable) to
``workspace_incoming_webhooks``: a delivery the hook turned away (a bad signature, a refused verification, the hook switched
off), recorded only when the URL's token matched the hook, never with the payload (routes/hooks/hooks_controller.py). Until
now a refusal reached only the server log. Every existing webhook starts at 0 / null.

Revision ID: a8e3c51d7f42
Revises: f3d8a1c6e927
Create Date: 2026-11-03 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8e3c51d7f42"
down_revision: str | None = "f3d8a1c6e927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("refused_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("last_refused_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_refused_reason", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.drop_column("last_refused_reason")
        batch_op.drop_column("last_refused_at")
        batch_op.drop_column("refused_count")
