"""mcp upload links

Revision ID: 7a38989125da
Revises: 86af6abd02c3
Create Date: 2026-10-18 18:11:28.280423

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "7a38989125da"
down_revision: str | None = "86af6abd02c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_upload_links",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("token_lookup", sa.String(length=64), nullable=False),
        sa.Column("grant_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("user_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("alt_text", sa.String(length=1000), nullable=True),
        sa.Column("expires_at", marvin.db.migration_types.NaiveDateTime(), nullable=False),
        sa.Column("used_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("asset_id", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("created_ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["grant_id"], ["oauth_grants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_lookup", name="uq_mcp_upload_links_token_lookup"),
    )
    with op.batch_alter_table("mcp_upload_links", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_mcp_upload_links_created_at"), ["created_at"], unique=False)
        batch_op.create_index("ix_mcp_upload_links_expires_at", ["expires_at"], unique=False)
        batch_op.create_index("ix_mcp_upload_links_grant_id", ["grant_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("mcp_upload_links", schema=None) as batch_op:
        batch_op.drop_index("ix_mcp_upload_links_grant_id")
        batch_op.drop_index("ix_mcp_upload_links_expires_at")
        batch_op.drop_index(batch_op.f("ix_mcp_upload_links_created_at"))

    op.drop_table("mcp_upload_links")
