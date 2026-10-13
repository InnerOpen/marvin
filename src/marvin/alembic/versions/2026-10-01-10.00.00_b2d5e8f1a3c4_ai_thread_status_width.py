"""ai_threads.status: String(16) → String(32)

Slice C ("ask first"): a parked run sets the thread status to "awaiting_approval" — 17 characters,
one more than the column allowed. SQLite ignores the length; Postgres would reject the first park.
Widened to 32 so no future status has to come back here.

Revision ID: b2d5e8f1a3c4
Revises: a1c9d4e7f2b3
Create Date: 2026-10-01 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d5e8f1a3c4"
down_revision: str | None = "a1c9d4e7f2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_threads") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=16), type_=sa.String(length=32), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("ai_threads") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=32), type_=sa.String(length=16), existing_nullable=False)
