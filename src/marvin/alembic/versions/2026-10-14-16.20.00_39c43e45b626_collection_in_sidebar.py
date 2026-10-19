"""collection in sidebar

Revision ID: 39c43e45b626
Revises: 15b18d5af5eb
Create Date: 2026-10-14 16:20:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "39c43e45b626"
down_revision: str | None = "15b18d5af5eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("collections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("in_sidebar", sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("collections", schema=None) as batch_op:
        batch_op.drop_column("in_sidebar")
