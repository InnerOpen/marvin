"""workspace own backups

Revision ID: 4166a87cee01
Revises: 10b5c7c078c7
Create Date: 2026-10-14 21:10:32.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "4166a87cee01"
down_revision: str | None = "10b5c7c078c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "fk_workspace_storage_settings_backup_connection_id"


def upgrade() -> None:
    with op.batch_alter_table("workspace_storage_connections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("purpose", sa.String(), server_default="assets", nullable=False))

    with op.batch_alter_table("workspace_storage_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("backup_connection_id", marvin.db.migration_types.GUID(), nullable=True))
        batch_op.add_column(sa.Column("backup_keep", sa.Integer(), server_default="7", nullable=False))
        batch_op.create_foreign_key(FK, "workspace_storage_connections", ["backup_connection_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("workspace_storage_settings", schema=None) as batch_op:
        batch_op.drop_constraint(FK, type_="foreignkey")
        batch_op.drop_column("backup_keep")
        batch_op.drop_column("backup_connection_id")

    with op.batch_alter_table("workspace_storage_connections", schema=None) as batch_op:
        batch_op.drop_column("purpose")
