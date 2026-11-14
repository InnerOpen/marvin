"""entry type picture presets: entry_types.picture_presets_json (named recipes of picture treatments its templates name)

Revision ID: 7c2e5a91d4f3
Revises: 4b537ff0c66a
Create Date: 2026-11-13 21:10:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7c2e5a91d4f3"
down_revision: str | None = "4b537ff0c66a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("entry_types", schema=None) as batch_op:
        batch_op.add_column(sa.Column("picture_presets_json", sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("entry_types", schema=None) as batch_op:
        batch_op.drop_column("picture_presets_json")
