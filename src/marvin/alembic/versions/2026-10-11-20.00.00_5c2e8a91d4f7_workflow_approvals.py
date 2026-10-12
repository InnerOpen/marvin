"""workflow approvals: a run waiting at an Approval step

Schema (additive):
  - ``workflow_approvals`` — one row per run parked at an Approval step: the workflow, the run that parked and the one
    that went on, the step and target, the message and who may decide (a workspace role), the status
    (pending|approved|denied|expired|stale), the run's snapshot, the entry and its version, when it expires, and who
    decided, when, with what note. Deleted with the workspace or the workflow.

Revision ID: 5c2e8a91d4f7
Revises: 128961a76aa8
Create Date: 2026-10-11 20:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "5c2e8a91d4f7"
down_revision: str | None = "128961a76aa8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_approvals",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("automation_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("execution_id", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("resumed_execution_id", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(length=100), nullable=True),
        sa.Column("target_index", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("min_role", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("entry_id", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("entry_version", sa.String(length=64), nullable=True),
        sa.Column("expires_at", marvin.db.migration_types.NaiveDateTime(), nullable=False),
        sa.Column("decided_by", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("decided_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["automation_id"], ["workspace_automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["automation_executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resumed_execution_id"], ["automation_executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        for column in ("group_id", "automation_id", "status", "entry_id", "expires_at", "created_at"):
            batch_op.create_index(batch_op.f(f"ix_workflow_approvals_{column}"), [column], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        for column in ("group_id", "automation_id", "status", "entry_id", "expires_at", "created_at"):
            batch_op.drop_index(batch_op.f(f"ix_workflow_approvals_{column}"))
    op.drop_table("workflow_approvals")
