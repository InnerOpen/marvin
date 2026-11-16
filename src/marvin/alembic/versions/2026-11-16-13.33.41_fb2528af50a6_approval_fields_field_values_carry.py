"""workflow approvals: boxes the approver may change before approving, what was approved, and a Redo's carried text

Adds three nullable JSON columns to ``workflow_approvals`` (services/automation/approvals.py): ``fields`` (an approval
step's editable boxes as asked, each with its prefilled text), ``field_values`` (the text approved) and ``carry`` (the
text a Redo with changes hands to the next approval on the same entry). Null (every existing approval) means the step
had no boxes.

No backfill. Downgrade drops the columns.

Revision ID: fb2528af50a6
Revises: 7c2e5a91d4f3
Create Date: 2026-11-16 13:33:41.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fb2528af50a6"
down_revision: str | None = "7c2e5a91d4f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("fields", "field_values", "carry")


def upgrade() -> None:
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        for name in COLUMNS:
            batch_op.add_column(sa.Column(name, sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        for name in reversed(COLUMNS):
            batch_op.drop_column(name)
