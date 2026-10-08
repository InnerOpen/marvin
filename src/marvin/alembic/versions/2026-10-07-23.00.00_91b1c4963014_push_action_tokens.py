"""push action tokens: Approve / Deny on an AI-approval notification

Schema (additive):
  - ``push_action_tokens`` — one row per approval push one tap may decide: the SHA-256 of its single-use
    token (never the token), the user and the root thread it decides, the park it was minted for, when it
    expires and when it was used. Deleted with the user or the thread.

Revision ID: 91b1c4963014
Revises: 51102e463fce
Create Date: 2026-10-07 23:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "91b1c4963014"
down_revision: str | None = "51102e463fce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_action_tokens",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("user_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("thread_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("parked_at", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", marvin.db.migration_types.NaiveDateTime(), nullable=False),
        sa.Column("used_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["thread_id"], ["ai_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_push_action_tokens_token_hash"),
    )
    with op.batch_alter_table("push_action_tokens", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_push_action_tokens_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_push_action_tokens_expires_at"), ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_push_action_tokens_thread_id"), ["thread_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_push_action_tokens_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("push_action_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_push_action_tokens_user_id"))
        batch_op.drop_index(batch_op.f("ix_push_action_tokens_thread_id"))
        batch_op.drop_index(batch_op.f("ix_push_action_tokens_expires_at"))
        batch_op.drop_index(batch_op.f("ix_push_action_tokens_created_at"))

    op.drop_table("push_action_tokens")
