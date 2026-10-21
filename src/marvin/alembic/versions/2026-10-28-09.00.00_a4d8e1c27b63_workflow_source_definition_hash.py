"""workflow source definition hash: remember the version a blueprint installed

Adds nullable ``source_definition_hash`` to ``workspace_automations``: the sha256 of the canonical JSON
of the definition a blueprint installed (or last updated to). A workflow whose definition no longer hashes
to it was edited in the workspace, which is what lets the integration card tell "the integration shipped
a new version" from "someone changed it here".

No backfill: the provider's declared definition is plugin code, which a migration can't import. A row with
no hash is judged at read time (``blueprint_state`` → ``differs``) and gets one at its next Update.

Downgrade drops the column.

Revision ID: a4d8e1c27b63
Revises: f2a6c8d41b95
Create Date: 2026-10-28 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4d8e1c27b63"
down_revision: str | None = "f2a6c8d41b95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_automations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_definition_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_automations", schema=None) as batch_op:
        batch_op.drop_column("source_definition_hash")
