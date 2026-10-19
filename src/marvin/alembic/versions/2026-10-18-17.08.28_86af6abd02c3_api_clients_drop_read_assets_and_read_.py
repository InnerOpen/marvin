"""api clients: drop read:assets and read:resources

The publishing API no longer serves assets or resources (4e71f420, 73daa0a0): entries carry their own. Clients
created before still hold the two keys, which the admin form lists under "Other". Nothing checks them; this
removes them. Downgrade leaves them out: they gate nothing, so there is nothing to restore.

Revision ID: 86af6abd02c3
Revises: 4d8eabca4995
Create Date: 2026-10-18 17:08:28.226343

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "86af6abd02c3"
down_revision: str | None = "4d8eabca4995"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETIRED = frozenset({"read:assets", "read:resources"})


def upgrade() -> None:
    bind = op.get_bind()
    clients = sa.table("api_clients", sa.column("id"), sa.column("permissions", sa.JSON))
    for client_id, permissions in bind.execute(sa.select(clients.c.id, clients.c.permissions)).all():
        if isinstance(permissions, str):  # SQLite hands JSON back as text
            permissions = json.loads(permissions)
        if isinstance(permissions, dict) and RETIRED & permissions.keys():
            kept = {key: value for key, value in permissions.items() if key not in RETIRED}
            bind.execute(clients.update().where(clients.c.id == client_id).values(permissions=kept))


def downgrade() -> None:
    pass
