"""incoming webhooks: signature scheme + signed URL

Adds `signature_scheme` (which HMAC construction the sender uses; null = the original hex HMAC of the
raw body) and `signature_url` (the public notification URL a sender signs alongside the body —
Square's scheme). Both nullable; existing webhooks verify exactly as before. Additive — safe on
Postgres and SQLite.

Revision ID: c4e8a2f6b9d1
Revises: b2d5e8f1a3c4
Create Date: 2026-10-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a2f6b9d1"
down_revision: str | None = "b2d5e8f1a3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("signature_scheme", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("signature_url", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_incoming_webhooks", schema=None) as batch_op:
        batch_op.drop_column("signature_url")
        batch_op.drop_column("signature_scheme")
