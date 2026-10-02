"""site rebuild requests: coalesce rebuilds per workspace

Adds `site_rebuild_requests` — one row per workspace with a rebuild waiting to be sent, so a burst of
`request_site_rebuild` calls (a bulk edit firing a workflow per entry) becomes one site build.
Additive — safe on Postgres and SQLite.

Revision ID: e6a1c4d8b3f7
Revises: d5f9b3a7c2e4
Create Date: 2026-10-02 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "e6a1c4d8b3f7"
down_revision: str | None = "d5f9b3a7c2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_rebuild_requests",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("first_requested_at", marvin.db.migration_types.NaiveDateTime(), nullable=False),
        sa.Column("last_requested_at", marvin.db.migration_types.NaiveDateTime(), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id"),
    )
    with op.batch_alter_table("site_rebuild_requests", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_site_rebuild_requests_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("site_rebuild_requests", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_site_rebuild_requests_created_at"))
    op.drop_table("site_rebuild_requests")
