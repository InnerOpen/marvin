"""a daily limit on paid approvals: the workspace's setting, and whether an approval guards a paid step

Adds ``group_preferences.paid_approvals_per_day`` (nullable integer: null is no limit) and
``workflow_approvals.paid`` (boolean, false): an approval that guards a paid integration step, decided when it parked
(services/integrations/estimate.py), which the daily limit counts. Every existing approval is not paid: the limit counts
from now on.

Downgrade drops both columns.

Revision ID: b7596d29dc7c
Revises: fb2528af50a6
Create Date: 2026-11-16 14:31:48.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7596d29dc7c"
down_revision: str | None = "fb2528af50a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("paid_approvals_per_day", sa.Integer(), nullable=True))
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("paid", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("workflow_approvals", schema=None) as batch_op:
        batch_op.drop_column("paid")
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("paid_approvals_per_day")
