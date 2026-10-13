"""agent hand-offs: workspace_agents.handoff_hint + ai_threads.parent_thread_id

Slice D ("Marvin as router"): a specialist's roster line gets a one-line hint, and a hand-off opens
a child thread that points at the router's thread. Both additive and nullable. The self-referential
FK is created inline in batch mode (SQLite rebuilds the table; Postgres adds the constraint).

Revision ID: a1c9d4e7f2b3
Revises: f7b3c4d5e6a8
Create Date: 2026-09-30 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "a1c9d4e7f2b3"
down_revision: str | None = "f7b3c4d5e6a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_agents") as batch_op:
        batch_op.add_column(sa.Column("handoff_hint", sa.String(length=300), nullable=True))

    with op.batch_alter_table("ai_threads") as batch_op:
        batch_op.add_column(sa.Column("parent_thread_id", marvin.db.migration_types.GUID(), nullable=True))
        batch_op.create_foreign_key("fk_ai_threads_parent_thread_id", "ai_threads", ["parent_thread_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_ai_threads_parent_thread_id", ["parent_thread_id"])


def downgrade() -> None:
    with op.batch_alter_table("ai_threads") as batch_op:
        batch_op.drop_index("ix_ai_threads_parent_thread_id")
        batch_op.drop_constraint("fk_ai_threads_parent_thread_id", type_="foreignkey")
        batch_op.drop_column("parent_thread_id")

    with op.batch_alter_table("workspace_agents") as batch_op:
        batch_op.drop_column("handoff_hint")
