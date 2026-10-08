"""automation agent draft: which workflows an agent may revise

Schema (additive):
  - ``workspace_automations.agent_draft`` — true while a workflow is an agent's draft that no person has saved since
    (draft_workflow sets it; any editor/REST save clears it). update_workflow_draft revises only these, so an agent
    never overwrites a person's switched-off workflow that happens to share a name. Existing rows: false.

Revision ID: c4e8a1f05b27
Revises: 8d7926207984
Create Date: 2026-10-08 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4e8a1f05b27"
down_revision: str | None = "8d7926207984"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_automations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agent_draft", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("workspace_automations", schema=None) as batch_op:
        batch_op.drop_column("agent_draft")
