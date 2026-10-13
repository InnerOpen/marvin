"""incoming webhooks: custom signature config

Adds `signature_config` (JSON): the construction a `custom` signature scheme verifies with —
algorithm, encoding, message template, header, prefix, key format, timestamp tolerance. Null for
presets. Additive — safe on Postgres and SQLite.

Revision ID: d5f9b3a7c2e4
Revises: c4e8a2f6b9d1
Create Date: 2026-10-02 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5f9b3a7c2e4"
down_revision: str | None = "c4e8a2f6b9d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("signature_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.drop_column("signature_config")
