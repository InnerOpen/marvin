"""platform secrets

A secret scope for Marvin itself: `workspace_secrets.group_id` becomes nullable, and a NULL `group_id` is a platform
secret (the platform SMTP password, platform alert channels). NULLs are distinct in a unique constraint, so a partial
unique index keeps one platform secret per slug.

Revision ID: d6896d6a5e2e
Revises: 7a38989125da
Create Date: 2026-10-18 21:48:07.675639

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "d6896d6a5e2e"
down_revision: str | None = "7a38989125da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_secrets", schema=None) as batch_op:
        batch_op.alter_column("group_id", existing_type=mt.GUID(), nullable=True)
        batch_op.create_index(
            "uq_workspace_secrets_platform_slug",
            ["slug"],
            unique=True,
            postgresql_where=sa.text("group_id IS NULL"),
            sqlite_where=sa.text("group_id IS NULL"),
        )


def downgrade() -> None:
    # Platform secrets have no workspace to belong to: they go before the column is NOT NULL again.
    op.execute(sa.text("DELETE FROM workspace_secrets WHERE group_id IS NULL"))
    with op.batch_alter_table("workspace_secrets", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_workspace_secrets_platform_slug",
            postgresql_where=sa.text("group_id IS NULL"),
            sqlite_where=sa.text("group_id IS NULL"),
        )
        batch_op.alter_column("group_id", existing_type=mt.GUID(), nullable=False)
