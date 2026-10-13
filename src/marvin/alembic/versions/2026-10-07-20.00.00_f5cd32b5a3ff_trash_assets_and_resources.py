"""assets, resources: the Trash

Adds `trashed_at` (indexed) and `trashed_by` to assets and resources. A row with `trashed_at` set is in the
Trash: hidden from every listing, the publishing API and the AI until it is restored (both cleared) or the
Trash is emptied (row deleted; for an asset, its file too). `trashed_by` is the user who moved it there, or
null for a system move; like an entry's metadata_json.trash record it carries no foreign key. Every existing
row is null, i.e. not trashed. Additive — safe on Postgres and SQLite.

Revision ID: f5cd32b5a3ff
Revises: cfbbd1cc67e4
Create Date: 2026-10-07 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "f5cd32b5a3ff"
down_revision: str | None = "cfbbd1cc67e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("assets", "resources")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("trashed_at", marvin.db.migration_types.NaiveDateTime(), nullable=True))
            batch_op.add_column(sa.Column("trashed_by", marvin.db.migration_types.GUID(), nullable=True))
            batch_op.create_index(f"ix_{table}_trashed_at", ["trashed_at"], unique=False)


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table}_trashed_at")
            batch_op.drop_column("trashed_by")
            batch_op.drop_column("trashed_at")
