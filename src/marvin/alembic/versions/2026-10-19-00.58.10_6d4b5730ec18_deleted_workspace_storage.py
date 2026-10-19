"""deleted workspace storage

Stored files of a deleted workspace are recorded (location, key prefix, size, deletion time) so a daily system task
can purge them after a 30-day grace period instead of leaving them orphaned (services/storage/deleted_workspaces.py).
A new table; nothing else changes. Downgrade drops it.

Revision ID: 6d4b5730ec18
Revises: a225a6254088
Create Date: 2026-10-19 00:58:10.942736

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "6d4b5730ec18"
down_revision: str | None = "a225a6254088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deleted_workspace_storage",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("workspace_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("workspace_name", sa.String(), nullable=False),
        sa.Column("workspace_slug", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("prefix", sa.String(), nullable=True),
        sa.Column("extra_keys", sa.JSON(), nullable=False),
        sa.Column("object_count", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("connection", sa.JSON(), nullable=True),
        sa.Column("deleted_at", marvin.db.migration_types.NaiveDateTime(), nullable=False),
        sa.Column("state", sa.String(), server_default="pending", nullable=False),
        sa.Column("state_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("purged_objects", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("deleted_workspace_storage", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_deleted_workspace_storage_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_deleted_workspace_storage_deleted_at"), ["deleted_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_deleted_workspace_storage_state"), ["state"], unique=False)
        batch_op.create_index(batch_op.f("ix_deleted_workspace_storage_workspace_id"), ["workspace_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("deleted_workspace_storage", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_deleted_workspace_storage_workspace_id"))
        batch_op.drop_index(batch_op.f("ix_deleted_workspace_storage_state"))
        batch_op.drop_index(batch_op.f("ix_deleted_workspace_storage_deleted_at"))
        batch_op.drop_index(batch_op.f("ix_deleted_workspace_storage_created_at"))

    op.drop_table("deleted_workspace_storage")
