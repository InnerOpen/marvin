"""incoming webhooks: optional HMAC signature verification

Adds `signing_secret_ref` (workspace secret slug holding the sender's signing key) and
`signature_header` (header carrying `sha256=<hex>`) to workspace_incoming_webhooks. Both nullable;
existing webhooks keep URL-token-only auth. Additive — safe on Postgres and SQLite.

Revision ID: b7d2e9a4c1f0
Revises: 9c3a1e7b52d4
Create Date: 2026-09-11 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2e9a4c1f0"
down_revision: str | None = "9c3a1e7b52d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("signing_secret_ref", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("signature_header", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.drop_column("signature_header")
        batch_op.drop_column("signing_secret_ref")
