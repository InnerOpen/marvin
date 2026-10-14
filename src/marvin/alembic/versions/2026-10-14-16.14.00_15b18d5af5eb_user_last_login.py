"""user last login

Revision ID: 15b18d5af5eb
Revises: f179fc8388df
Create Date: 2026-10-14 16:14:00.050452

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "15b18d5af5eb"
down_revision: str | None = "f179fc8388df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_login_at", marvin.db.migration_types.NaiveDateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("last_login_at")
