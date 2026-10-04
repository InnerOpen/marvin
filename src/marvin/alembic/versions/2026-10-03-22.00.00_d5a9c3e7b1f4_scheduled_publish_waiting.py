"""scheduled publish waiting

Adds `entries.scheduled_publish_blocked` (nullable JSON): why the Publish Scheduled Entries task is
holding a due entry back (the publish gate's issues, or "waiting for approval"), so the editor can say
so and the task notifies once per distinct reason. And `group_preferences.scheduled_publish_requires_approval`
(default false): when on, the task only publishes due entries whose status is `approved`. Additive —
safe on Postgres and SQLite.

Revision ID: d5a9c3e7b1f4
Revises: 5bceae3a4076
Create Date: 2026-10-03 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5a9c3e7b1f4"
down_revision: str | None = "5bceae3a4076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("scheduled_publish_blocked", sa.JSON(none_as_null=True), nullable=True))
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("scheduled_publish_requires_approval", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("scheduled_publish_requires_approval")
    with op.batch_alter_table("entries", schema=None) as batch_op:
        batch_op.drop_column("scheduled_publish_blocked")
