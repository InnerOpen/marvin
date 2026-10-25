"""social inbox: what each item needs (its bucket)

Adds ``bucket``, ``bucket_source`` (strings) and ``bucket_at`` (timestamp), all nullable, to ``social_inbox_items``: one of
six fixed buckets (keyword, lead, question, feedback, support, noise — services/integrations/social_buckets.py) and who
sorted it (rule, heuristic, ai, person). Items are sorted when first stored; every existing item starts unsorted.

Revision ID: c3a7e1d95b28
Revises: b6d2f8a41c93
Create Date: 2026-11-05 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "c3a7e1d95b28"
down_revision: str | None = "b6d2f8a41c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bucket", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("bucket_source", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("bucket_at", marvin.db.migration_types.AwareDateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("social_inbox_items", schema=None) as batch_op:
        batch_op.drop_column("bucket_at")
        batch_op.drop_column("bucket_source")
        batch_op.drop_column("bucket")
