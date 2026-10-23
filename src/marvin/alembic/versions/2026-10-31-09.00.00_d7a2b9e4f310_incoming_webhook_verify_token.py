"""incoming webhooks: answering a sender's verification request

Adds three nullable columns to ``workspace_incoming_webhooks`` (services/webhooks/incoming_verification.py):
``verification_scheme`` (an integration's scheme, or ``custom``), ``verification_config`` (JSON, for ``custom``) and
``verify_token_ref`` (the workspace secret the sender's verify token must match). Null — every existing webhook — means
a GET is refused, as now.

No backfill. Downgrade drops the column.

Revision ID: d7a2b9e4f310
Revises: c6f1a8d94e27
Create Date: 2026-10-31 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a2b9e4f310"
down_revision: str | None = "c6f1a8d94e27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("verification_scheme", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("verification_config", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("verify_token_ref", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.drop_column("verify_token_ref")
        batch_op.drop_column("verification_config")
        batch_op.drop_column("verification_scheme")
