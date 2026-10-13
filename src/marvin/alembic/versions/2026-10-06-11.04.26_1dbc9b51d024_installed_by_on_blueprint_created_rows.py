"""installed by: provenance on blueprint-created rows

Adds ``source_integration_id`` (FK → integrations, ON DELETE SET NULL) and ``source_blueprint`` (the
blueprint's slug) to everything a blueprint can create: ``workspace_automations``,
``scheduled_tasks``, ``workspace_incoming_webhooks``, ``integration_event_subscriptions`` and
``collections``. From now on ``services/blueprints/apply.py`` sets them; NULL means a person made it.

Backfill — existing rows are matched to the integration that installed them, per workspace, and
left NULL whenever that isn't clear:

1. **By blueprint slug.** ``_BLUEPRINTS`` is a snapshot (2026-10-06) of the blueprints the
   integration packages ship (a migration must not import plugin code that may be absent or newer).
   A row whose slug is one of a provider's blueprint slugs *for that kind* is attributed to the
   workspace's integration of that provider — only when the workspace has exactly one. Both columns
   are set. An integration event subscription carries its integration already, so it matches when
   that integration's provider ships a subscription blueprint with the same event and action (the
   same identity ``apply.py`` uses to decide a subscription blueprint is already applied).
2. **By name prefix.** Otherwise a name starting ``"<Provider>: "`` (the naming every provider
   workflow uses — "Square: …", "Buttondown: …", "Cloudflare Pages: …", "n8n: …") is attributed to
   the workspace's one integration of that provider. Only ``source_integration_id`` is set; which
   blueprint it was isn't known. The colon is required: "n8n ping" is someone's own workflow.
3. Anything else — platform tasks, system collections, rows of a provider with zero or several
   integrations in the workspace — stays NULL.

Downgrade drops the columns.

Revision ID: 1dbc9b51d024
Revises: cba7c23b692e
Create Date: 2026-10-06 11:04:26.560265

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "1dbc9b51d024"
down_revision: str | None = "cba7c23b692e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table → the blueprint kind that creates its rows
_TABLES = {
    "workspace_automations": "workflow",
    "scheduled_tasks": "scheduled_task",
    "workspace_incoming_webhooks": "incoming_webhook",
    "integration_event_subscriptions": "event_subscription",
    "collections": "collection",
}

# provider → kind → blueprint slugs (event subscriptions: slug → (event_type, action)).
# Snapshot of the integration packages' blueprints, 2026-10-06.
_BLUEPRINTS: dict[str, dict] = {
    "buttondown": {
        "incoming_webhook": ["buttondown"],
        "workflow": [
            "buttondown-subscribe-on-signup",
            "buttondown-subscriber-confirmed",
            "buttondown-subscriber-unsubscribed",
            "buttondown-issue-on-publish",
        ],
        "collection": ["confirmed-subscribers", "unsubscribed"],
    },
    "cloudflare_pages": {
        "incoming_webhook": ["cloudflare-pages"],
        "workflow": ["cloudflare-pages-deploy-started", "cloudflare-pages-deploy-succeeded", "cloudflare-pages-deploy-failed"],
    },
    "instagram": {
        "collection": ["social-auto-responses", "social-sent"],
        "scheduled_task": ["instagram-auto-reply", "instagram-token-refresh"],
    },
    "n8n": {
        "incoming_webhook": ["n8n"],
        "workflow": ["n8n-record-result"],
        "collection": ["n8n-failed", "n8n-in-flight"],
    },
    "square": {
        "incoming_webhook": ["square-events"],
        "workflow": [
            "square-list-for-sale",
            "square-mark-sold",
            "square-close-when-sold",
            "square-close-when-withdrawn",
            "square-close-when-unpublished",
            "square-close-when-archived",
        ],
    },
    "slack": {
        "event_subscription": {"announce-published-entries": ("entry_published", "send_message")},
    },
}

_NAME_PREFIXES = {
    "Buttondown: ": "buttondown",
    "Cloudflare Pages: ": "cloudflare_pages",
    "Instagram: ": "instagram",
    "n8n: ": "n8n",
    "Slack: ": "slack",
    "Square: ": "square",
}


def _fk(table: str) -> str:
    return f"fk_{table}_source_integration_id"


def _match(kind: str, row, integrations: dict) -> tuple:
    """(source_integration_id, source_blueprint) for one row, or (None, None).

    ``integrations``: this workspace's {provider: [integration ids]}, plus ``by_id`` {id: provider}."""
    if kind == "event_subscription":
        provider = integrations["by_id"].get(row.integration_id)
        for slug, wiring in (_BLUEPRINTS.get(provider, {}).get(kind) or {}).items():
            if wiring == (row.event_type, row.action):
                return row.integration_id, slug
        return None, None

    for provider, kinds in _BLUEPRINTS.items():
        if row.slug in kinds.get(kind, ()):
            ids = integrations.get(provider, [])
            return (ids[0], row.slug) if len(ids) == 1 else (None, None)
    for prefix, provider in _NAME_PREFIXES.items():
        if (row.name or "").startswith(prefix):
            ids = integrations.get(provider, [])
            return (ids[0], None) if len(ids) == 1 else (None, None)
    return None, None


def _backfill(bind) -> None:
    integrations_t = sa.table("integrations", sa.column("id", mt.GUID()), sa.column("group_id", mt.GUID()), sa.column("provider", sa.String()))
    by_group: dict = {}
    for row in bind.execute(sa.select(integrations_t.c.id, integrations_t.c.group_id, integrations_t.c.provider)):
        group = by_group.setdefault(row.group_id, {"by_id": {}})
        group.setdefault(row.provider, []).append(row.id)
        group["by_id"][row.id] = row.provider

    for table, kind in _TABLES.items():
        cols = [sa.column("id", mt.GUID()), sa.column("group_id", mt.GUID())]
        cols += (
            [sa.column("integration_id", mt.GUID()), sa.column("event_type", sa.String()), sa.column("action", sa.String())]
            if kind == "event_subscription"
            else [sa.column("slug", sa.String()), sa.column("name", sa.String())]
        )
        cols += [sa.column("source_integration_id", mt.GUID()), sa.column("source_blueprint", sa.String())]
        t = sa.table(table, *cols)
        for row in bind.execute(sa.select(*[c for c in t.c if not c.name.startswith("source_")])).fetchall():
            if row.group_id is None or row.group_id not in by_group:
                continue  # platform rows, or a workspace with no integrations
            integration_id, blueprint = _match(kind, row, by_group[row.group_id])
            if integration_id is not None:
                bind.execute(t.update().where(t.c.id == row.id).values(source_integration_id=integration_id, source_blueprint=blueprint))


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("source_integration_id", mt.GUID(), nullable=True))
            batch_op.add_column(sa.Column("source_blueprint", sa.String(), nullable=True))
            batch_op.create_index(f"ix_{table}_source_integration_id", ["source_integration_id"], unique=False)
            batch_op.create_foreign_key(_fk(table), "integrations", ["source_integration_id"], ["id"], ondelete="SET NULL")
    _backfill(op.get_bind())


def downgrade() -> None:
    for table in reversed(_TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(_fk(table), type_="foreignkey")
            batch_op.drop_index(f"ix_{table}_source_integration_id")
            batch_op.drop_column("source_blueprint")
            batch_op.drop_column("source_integration_id")
