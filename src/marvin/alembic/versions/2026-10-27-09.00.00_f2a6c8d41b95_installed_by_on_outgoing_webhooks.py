"""installed by: provenance on outgoing webhooks

Adds ``source_integration_id`` (FK → integrations, ON DELETE SET NULL) and ``source_blueprint`` to
``webhook_urls`` (outgoing webhooks), the same two columns ``InstalledByMixin`` puts on the other rows
a blueprint can create. NULL means a person made it.

Backfill — a row is labelled only when it *exactly* matches a known plugin blueprint: the same name
and the same URL host, in a workspace with exactly one integration of that provider. ``_KNOWN`` is a
snapshot (2026-10-27) of the outgoing webhooks the integration packages declare, and it is empty:
no plugin blueprint creates an outgoing webhook today (blueprints build incoming webhooks, workflows,
collections, tasks and event subscriptions). The machinery is here so that a snapshot entry is all a
future plugin needs. Every other row stays NULL ("yours").

Downgrade drops the columns.

Revision ID: f2a6c8d41b95
Revises: e7c3a9b15d42
Create Date: 2026-10-27 09:00:00.000000

"""

from collections.abc import Sequence
from urllib.parse import urlparse

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "f2a6c8d41b95"
down_revision: str | None = "e7c3a9b15d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "webhook_urls"
_FK = "fk_webhook_urls_source_integration_id"
_INDEX = "ix_webhook_urls_source_integration_id"

# Snapshot of outgoing webhooks that plugin blueprints declare: {"provider", "slug" (the blueprint), "name", "host"}.
# Empty: none do yet.
_KNOWN: list[dict] = []


def _host(url) -> str:
    return (urlparse(str(url or "")).hostname or "").lower()


def _backfill(bind, known: list[dict] | None = None) -> None:
    known = _KNOWN if known is None else known
    if not known:
        return
    integrations_t = sa.table("integrations", sa.column("id", mt.GUID()), sa.column("group_id", mt.GUID()), sa.column("provider", sa.String()))
    by_group: dict = {}
    for row in bind.execute(sa.select(integrations_t.c.id, integrations_t.c.group_id, integrations_t.c.provider)):
        by_group.setdefault(row.group_id, {}).setdefault(row.provider, []).append(row.id)

    t = sa.table(
        _TABLE,
        sa.column("id", mt.GUID()),
        sa.column("group_id", mt.GUID()),
        sa.column("name", sa.String()),
        sa.column("url", sa.String()),
        sa.column("source_integration_id", mt.GUID()),
        sa.column("source_blueprint", sa.String()),
    )
    for row in bind.execute(sa.select(t.c.id, t.c.group_id, t.c.name, t.c.url).where(t.c.source_integration_id.is_(None))).fetchall():
        for blueprint in known:
            if row.name != blueprint["name"] or _host(row.url) != blueprint["host"].lower():
                continue
            ids = by_group.get(row.group_id, {}).get(blueprint["provider"], [])
            if len(ids) == 1:
                bind.execute(t.update().where(t.c.id == row.id).values(source_integration_id=ids[0], source_blueprint=blueprint["slug"]))
            break


def upgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_integration_id", mt.GUID(), nullable=True))
        batch_op.add_column(sa.Column("source_blueprint", sa.String(), nullable=True))
        batch_op.create_index(_INDEX, ["source_integration_id"], unique=False)
        batch_op.create_foreign_key(_FK, "integrations", ["source_integration_id"], ["id"], ondelete="SET NULL")
    _backfill(op.get_bind())


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_FK, type_="foreignkey")
        batch_op.drop_index(_INDEX)
        batch_op.drop_column("source_blueprint")
        batch_op.drop_column("source_integration_id")
