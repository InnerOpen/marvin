"""webhookmode: add the "workflow" value on Postgres

`WebhookMode.workflow` was added to the model after the initial schema, which created the Postgres
`webhookmode` enum with only generic/user/entries/event_driven. Saving a workflow-type webhook (the kind
blueprints create for Buttondown and friends) therefore failed on Postgres with an invalid enum value.

SQLite stores the column as plain text, so this is a no-op there. Downgrade leaves the value in place:
Postgres can't drop a single enum value, and rows may already use it.

Revision ID: 5b0e7d2c9a41
Revises: 1dbc9b51d024
Create Date: 2026-10-06 16:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b0e7d2c9a41"
down_revision: str | None = "1dbc9b51d024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # ADD VALUE can't run inside a transaction block on older Postgres.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE webhookmode ADD VALUE IF NOT EXISTS 'workflow'")


def downgrade() -> None:
    pass
