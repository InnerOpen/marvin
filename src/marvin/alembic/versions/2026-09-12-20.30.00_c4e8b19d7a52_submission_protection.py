"""submission protection: platform settings table + workspace override column

Adds the keyed `platform_settings` table (admin-editable, platform-wide JSON documents) and
`group_preferences.submission_protection_json` (per-workspace override; null fields inherit).
Additive — safe on Postgres and SQLite.

Revision ID: c4e8b19d7a52
Revises: b7d2e9a4c1f0
Create Date: 2026-09-12 20:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "c4e8b19d7a52"
down_revision: str | None = "b7d2e9a4c1f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("update_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_platform_settings_key"), "platform_settings", ["key"], unique=True)
    op.create_index(op.f("ix_platform_settings_created_at"), "platform_settings", ["created_at"], unique=False)
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("submission_protection_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("submission_protection_json")
    op.drop_index(op.f("ix_platform_settings_created_at"), table_name="platform_settings")
    op.drop_index(op.f("ix_platform_settings_key"), table_name="platform_settings")
    op.drop_table("platform_settings")
