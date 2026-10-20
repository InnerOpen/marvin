"""social inbox items: the comments, replies and mentions the engagement poll read

Schema (additive):
  - ``social_inbox_items`` — one row per (integration, network item id): the normalised item the 5-minute social
    engagement poll read (author, text, post, link), a status (new | seen | replied | hidden | liked) and a pointer to the
    ``social-reply-log`` entry when it was answered. Deleted with the workspace and with the integration; a daily system
    task (``prune_social_inbox_items``) drops rows older than 30 days.

Downgrade drops the table (the inbox then fills again from the next polls; the reply log, which is what stops a comment
being answered twice, is entries and stays).

Revision ID: 7c3f9a1e5b82
Revises: 5e1c7a9d3b24
Create Date: 2026-10-21 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "7c3f9a1e5b82"
down_revision: str | None = "5e1c7a9d3b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_inbox_items",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("integration_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("integration_slug", sa.String(), nullable=False),
        sa.Column("network", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("post_id", sa.String(), nullable=True),
        sa.Column("post_url", sa.String(), nullable=True),
        sa.Column("author_id", sa.String(), nullable=True),
        sa.Column("author_handle", sa.String(), nullable=True),
        sa.Column("author_name", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("posted_at", marvin.db.migration_types.AwareDateTime(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("first_seen_at", marvin.db.migration_types.AwareDateTime(), nullable=False),
        sa.Column("status", sa.String(), server_default="new", nullable=False),
        sa.Column("reply_log_slug", sa.String(), nullable=True),
        sa.Column("reply_mode", sa.String(), nullable=True),
        sa.Column("reply_rehearsal", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reply_id", sa.String(), nullable=True),
        sa.Column("replied_at", marvin.db.migration_types.AwareDateTime(), nullable=True),
        sa.Column("replied_by", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replied_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("integration_id", "item_id", name="uq_social_inbox_items_item"),
    )
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_social_inbox_items_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_social_inbox_items_group_id"), ["group_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_social_inbox_items_integration_id"), ["integration_id"], unique=False)
        batch_op.create_index("ix_social_inbox_items_first_seen", ["first_seen_at"], unique=False)
        batch_op.create_index("ix_social_inbox_items_group_posted", ["group_id", "posted_at"], unique=False)
        batch_op.create_index("ix_social_inbox_items_group_status", ["group_id", "status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.drop_index("ix_social_inbox_items_group_status")
        batch_op.drop_index("ix_social_inbox_items_group_posted")
        batch_op.drop_index("ix_social_inbox_items_first_seen")
        batch_op.drop_index(batch_op.f("ix_social_inbox_items_integration_id"))
        batch_op.drop_index(batch_op.f("ix_social_inbox_items_group_id"))
        batch_op.drop_index(batch_op.f("ix_social_inbox_items_created_at"))

    op.drop_table("social_inbox_items")
