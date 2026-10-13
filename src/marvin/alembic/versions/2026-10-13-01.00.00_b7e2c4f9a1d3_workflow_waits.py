"""workflow waits: a run waiting at a Wait step until a time

Schema (additive):
  - ``workflow_waits`` — one row per run parked at a Wait step: the workflow, the run that parked and the one that went
    on, the step and target, when it goes on (resume_at), the status (waiting|resumed|cancelled), the run's snapshot,
    the entry, and why it was cancelled. Deleted with the workspace or the workflow.

Revision ID: b7e2c4f9a1d3
Revises: d00dff591ea6
Create Date: 2026-10-13 01:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "b7e2c4f9a1d3"
down_revision: str | None = "d00dff591ea6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXED = ("group_id", "automation_id", "status", "entry_id", "resume_at", "created_at")


def upgrade() -> None:
    op.create_table(
        "workflow_waits",
        sa.Column("id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("group_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("automation_id", marvin.db.migration_types.GUID(), nullable=False),
        sa.Column("execution_id", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("resumed_execution_id", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(length=100), nullable=True),
        sa.Column("target_index", sa.Integer(), nullable=False),
        sa.Column("resume_at", marvin.db.migration_types.NaiveDateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("entry_id", marvin.db.migration_types.GUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["automation_id"], ["workspace_automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["automation_executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resumed_execution_id"], ["automation_executions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("workflow_waits", schema=None) as batch_op:
        for column in INDEXED:
            batch_op.create_index(batch_op.f(f"ix_workflow_waits_{column}"), [column], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("workflow_waits", schema=None) as batch_op:
        for column in INDEXED:
            batch_op.drop_index(batch_op.f(f"ix_workflow_waits_{column}"))
    op.drop_table("workflow_waits")
