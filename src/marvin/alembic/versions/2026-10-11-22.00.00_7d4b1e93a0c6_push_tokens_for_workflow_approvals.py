"""push tokens for workflow approvals: one-tap Approve / Deny on a waiting workflow run

Schema:
  - ``push_action_tokens.thread_id`` becomes nullable, and ``push_action_tokens.workflow_approval_id`` (FK
    ``workflow_approvals``, cascade) is added: a token decides an AI run's park or a waiting workflow run.

Revision ID: 7d4b1e93a0c6
Revises: 5c2e8a91d4f7
Create Date: 2026-10-11 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "7d4b1e93a0c6"
down_revision: str | None = "5c2e8a91d4f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("push_action_tokens", schema=None) as batch_op:
        batch_op.alter_column("thread_id", existing_type=marvin.db.migration_types.GUID(), nullable=True)
        batch_op.add_column(sa.Column("workflow_approval_id", marvin.db.migration_types.GUID(), nullable=True))
        batch_op.create_index(batch_op.f("ix_push_action_tokens_workflow_approval_id"), ["workflow_approval_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_push_action_tokens_workflow_approval_id", "workflow_approvals", ["workflow_approval_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    op.execute("DELETE FROM push_action_tokens WHERE thread_id IS NULL")
    with op.batch_alter_table("push_action_tokens", schema=None) as batch_op:
        batch_op.drop_constraint("fk_push_action_tokens_workflow_approval_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_push_action_tokens_workflow_approval_id"))
        batch_op.drop_column("workflow_approval_id")
        batch_op.alter_column("thread_id", existing_type=marvin.db.migration_types.GUID(), nullable=False)
