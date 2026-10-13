"""approval choices: an Approval step that asks for one of several

Schema (additive):
  - ``workflow_approvals.choices`` — the labels offered (JSON list), null for approve/deny.
  - ``workflow_approvals.choice`` — the label picked, once approved.

Revision ID: c9d4e7a2b1f8
Revises: b7e2c4f9a1d3
Create Date: 2026-10-13 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d4e7a2b1f8"
down_revision: str | None = "b7e2c4f9a1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_approvals") as batch:
        batch.add_column(sa.Column("choices", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("choice", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_approvals") as batch:
        batch.drop_column("choice")
        batch.drop_column("choices")
