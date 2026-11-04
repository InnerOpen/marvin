"""packages: a labelled bundle of blueprints a workspace installed, uploaded or built from its own content

Creates ``workspace_packages`` (one row per workspace and slug: name, description, version and the whole manifest, so it can be
downloaded again as it was installed) and adds a nullable, indexed ``source_package`` (the package's slug) to the four tables a package
can create or adopt rows in: ``workspace_automations``, ``collections``, ``scheduled_tasks`` and ``workspace_incoming_webhooks``.
NULL means in no package, which is every existing row.

Revision ID: c3f7a1d9b2e4
Revises: 84b33c929065
Create Date: 2026-11-08 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "c3f7a1d9b2e4"
down_revision: str | None = "84b33c929065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PACKAGED_TABLES = ("workspace_automations", "collections", "scheduled_tasks", "workspace_incoming_webhooks")


def upgrade() -> None:
    op.create_table(
        "workspace_packages",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("version", sa.String(length=64), nullable=False, server_default="1"),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("created_by", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "slug", name="uq_workspace_packages_group_slug"),
    )
    op.create_index("ix_workspace_packages_created_at", "workspace_packages", ["created_at"])
    op.create_index("ix_workspace_packages_group_id", "workspace_packages", ["group_id"])
    for table in PACKAGED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("source_package", sa.String(length=128), nullable=True))
            batch_op.create_index(f"ix_{table}_source_package", ["source_package"], unique=False)


def downgrade() -> None:
    for table in reversed(PACKAGED_TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table}_source_package")
            batch_op.drop_column("source_package")
    op.drop_index("ix_workspace_packages_group_id", table_name="workspace_packages")
    op.drop_index("ix_workspace_packages_created_at", table_name="workspace_packages")
    op.drop_table("workspace_packages")
