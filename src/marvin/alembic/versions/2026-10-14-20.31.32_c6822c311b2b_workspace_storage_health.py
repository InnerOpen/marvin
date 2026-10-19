"""workspace storage health

Revision ID: c6822c311b2b
Revises: f3a4ff1be7a3
Create Date: 2026-10-14 20:31:32.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c6822c311b2b"
down_revision: str | None = "f3a4ff1be7a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_storage_connections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("workspace_storage_connections", schema=None) as batch_op:
        batch_op.drop_column("consecutive_failures")
