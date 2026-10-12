"""workflow entry locks: one run of a workflow on an entry at a time

Schema (additive):
  - ``workflow_entry_locks`` — the turn a run of a workflow holds on an entry (holder, lease_until), unique per
    (workflow, entry). Deleted with the workflow.

Revision ID: 9a3f6c2e1b84
Revises: 7d4b1e93a0c6
Create Date: 2026-10-12 02:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "9a3f6c2e1b84"
down_revision: str | None = "7d4b1e93a0c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_entry_locks",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("automation_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("entry_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("holder", sa.String(length=32), nullable=False),
        sa.Column("lease_until", marvin.db.migration_types.NaiveDateTime(), nullable=False),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["automation_id"], ["workspace_automations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("automation_id", "entry_id", name="uq_workflow_entry_locks_turn"),
    )
    with op.batch_alter_table("workflow_entry_locks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workflow_entry_locks_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("workflow_entry_locks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_entry_locks_created_at"))
    op.drop_table("workflow_entry_locks")
