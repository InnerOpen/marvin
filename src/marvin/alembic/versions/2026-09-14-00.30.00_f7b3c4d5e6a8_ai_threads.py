"""add ai_threads + ai_thread_messages

Server-side agent conversations (Ask threads): the thread row carries the agent, owner, status and a
parked pending run (ask-first); messages are the user/assistant turns with their tool trace.
Additive CREATE TABLE — safe on Postgres and SQLite.

Revision ID: f7b3c4d5e6a8
Revises: e6a2b3c4d5f7
Create Date: 2026-09-14 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "f7b3c4d5e6a8"
down_revision: str | None = "e6a2b3c4d5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_threads",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("agent_slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("created_by", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("pending_json", sa.JSON(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_message_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_threads_group_id", "ai_threads", ["group_id"])
    op.create_index("ix_ai_threads_agent_slug", "ai_threads", ["agent_slug"])
    op.create_index("ix_ai_threads_created_by", "ai_threads", ["created_by"])
    op.create_index("ix_ai_threads_created_at", "ai_threads", ["created_at"])
    op.create_index("ix_ai_threads_group_last_message", "ai_threads", ["group_id", "last_message_at"])

    op.create_table(
        "ai_thread_messages",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("thread_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("steps_json", sa.JSON(), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("execution_id", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["thread_id"], ["ai_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_thread_messages_group_id", "ai_thread_messages", ["group_id"])
    op.create_index("ix_ai_thread_messages_created_at", "ai_thread_messages", ["created_at"])
    op.create_index("ix_ai_thread_messages_thread_seq", "ai_thread_messages", ["thread_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_ai_thread_messages_thread_seq", table_name="ai_thread_messages")
    op.drop_index("ix_ai_thread_messages_created_at", table_name="ai_thread_messages")
    op.drop_index("ix_ai_thread_messages_group_id", table_name="ai_thread_messages")
    op.drop_table("ai_thread_messages")
    op.drop_index("ix_ai_threads_group_last_message", table_name="ai_threads")
    op.drop_index("ix_ai_threads_created_at", table_name="ai_threads")
    op.drop_index("ix_ai_threads_created_by", table_name="ai_threads")
    op.drop_index("ix_ai_threads_agent_slug", table_name="ai_threads")
    op.drop_index("ix_ai_threads_group_id", table_name="ai_threads")
    op.drop_table("ai_threads")
