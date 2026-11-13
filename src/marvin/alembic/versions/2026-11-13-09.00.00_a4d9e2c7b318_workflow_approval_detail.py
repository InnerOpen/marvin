"""workflow approvals: the whole of a long question, folded away under its short message

Adds a nullable ``detail`` (text) to ``workflow_approvals`` (services/automation/approvals.py): an approval step's own
``detail``, or the full text of a message too long to show on a card. Null (every existing approval) means the message
is all there is.

No backfill. Downgrade drops the column.

Revision ID: a4d9e2c7b318
Revises: c3f7a1d9b2e4
Create Date: 2026-11-13 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4d9e2c7b318"
down_revision: str | None = "c3f7a1d9b2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("detail", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        batch_op.drop_column("detail")
