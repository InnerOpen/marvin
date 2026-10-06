"""group_preferences: per-workspace audit overrides

Adds ``group_preferences.audit_overrides_json``: ``{event_type: bool}`` for the event types whose Event Log
coverage a workspace admin changed from the catalog default (``CatalogEntry.audited``). Null (or a type left
out) means the catalog default. Security events are locked and ignore it.

Additive — safe on Postgres and SQLite.

Revision ID: e6c2a9f4b1d3
Revises: a78a8895a6a1
Create Date: 2026-10-05 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6c2a9f4b1d3"
down_revision: str | None = "a78a8895a6a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("audit_overrides_json", sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("audit_overrides_json")
