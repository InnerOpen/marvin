"""workspace notifications: Settings → Automation → Notifications, and integration alerts folded into it

Schema (additive):
  - ``group_preferences.notifications_json`` — where the workspace's alerts go (null takes the defaults) — and
    ``notifications_status_json``, each channel's last delivery;
  - ``workspace_alert_incidents`` — one open row per failing workflow or scheduled task, so it alerts once
    per incident and sends one "working again" note.

Data: the Integration alerts panel (Settings → Integrations → Alerts & health) wrote ordinary subscription
rows for ``integration_attention_needed``; it is replaced by the Notifications page, which delivers
integration alerts itself. So that every workspace's integration alerts keep going exactly where they went:

  - a workspace with a connection or a panel row gets explicit settings: email to its owners and admins takes
    integration alerts only if the panel's email row was on (new workspaces get them by default), and each
    panel chat row becomes a route taking only integration alerts (on or off as the row was);
  - an open alert's recorded channels are rewritten from those rows' ids to the new channels, so its
    "working again" notice still goes where the alert went;
  - the panel's rows are deleted: an email row on the "Integration Alert" system template sent to admins, and
    a chat row whose arguments are only the alert's ``{{title}}`` / ``{{summary}}``. Anything else on that
    event (set up on the Events page) is left alone.

Downgrade drops the schema; the panel's rows are not recreated (choose the routing again on the panel).

Revision ID: cfbbd1cc67e4
Revises: 8d2f6a1c4e93
Create Date: 2026-10-07 15:45:34.073864
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "cfbbd1cc67e4"
down_revision: str | None = "8d2f6a1c4e93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEEDED = "integration_attention_needed"
INTEGRATION_KIND = "integration_attention"
OTHER_KINDS = ["workflow_failed", "scheduled_task_failed", "ai_operation_failed", "webhook_delivery_failed"]
"""services/workspace_alerts.py's kinds as of this revision, but the integration one."""
MESSAGE_FIELDS = {"text", "body", "message", "content", "title", "subject"}
MESSAGE_VALUES = {"{{title}}", "{{summary}}", "*{{title}}*\n{{summary}}"}
"""What the panel wrote into a chat row's arguments: the alert's title and summary, nothing else."""


def panel_args(args) -> bool:
    """Whether a chat row's arguments are the panel's: only the alert's title and summary."""
    return isinstance(args, dict) and bool(args) and set(args) <= MESSAGE_FIELDS and all(v in MESSAGE_VALUES for v in args.values())


def settings_for(email_on: bool, routes: list[dict]) -> dict:
    """A migrated workspace's notification settings."""
    email: dict = {"enabled": True, "recipients": None}
    if not email_on:
        email["kinds"] = list(OTHER_KINDS)
    return {"types": {}, "email": email, "routes": routes}


def rewrite_channels(channels, email_ids: set[str], route_for: dict[str, str]) -> dict:
    """An open alert's recorded channels with the panel's rows swapped for the channels that replace them."""
    channels = dict(channels or {})
    email = [c for c in channels.get("email") or [] if c not in email_ids]
    integration = [c for c in channels.get("integration") or [] if c not in route_for]
    notify = set(channels.get("notify") or [])
    if len(email) != len(channels.get("email") or []):
        notify.add("email")
    notify |= {route_for[c] for c in channels.get("integration") or [] if c in route_for}
    return {"email": email, "integration": integration, "notify": sorted(notify)}


def _tables():
    meta = sa.MetaData()
    tables = {
        "integrations": sa.Table("integrations", meta, sa.Column("id", mt.GUID()), sa.Column("group_id", mt.GUID())),
        "templates": sa.Table(
            "email_templates", meta, sa.Column("id", mt.GUID()), sa.Column("group_id", mt.GUID()), sa.Column("template_type", sa.String())
        ),
        "email_subs": sa.Table(
            "email_event_subscriptions",
            meta,
            sa.Column("id", mt.GUID()),
            sa.Column("group_id", mt.GUID()),
            sa.Column("template_id", mt.GUID()),
            sa.Column("event_type", sa.String()),
            sa.Column("recipient_type", sa.String()),
            sa.Column("enabled", sa.Boolean()),
        ),
        "integration_subs": sa.Table(
            "integration_event_subscriptions",
            meta,
            sa.Column("id", mt.GUID()),
            sa.Column("group_id", mt.GUID()),
            sa.Column("integration_id", mt.GUID()),
            sa.Column("event_type", sa.String()),
            sa.Column("action", sa.String()),
            sa.Column("args", sa.JSON()),
            sa.Column("enabled", sa.Boolean()),
        ),
        "prefs": sa.Table(
            "group_preferences", meta, sa.Column("id", mt.GUID()), sa.Column("group_id", mt.GUID()), sa.Column("notifications_json", sa.JSON())
        ),
        "alerts": sa.Table(
            "integration_alerts",
            meta,
            sa.Column("id", mt.GUID()),
            sa.Column("group_id", mt.GUID()),
            sa.Column("status", sa.String()),
            sa.Column("channels", sa.JSON()),
        ),
    }
    return tables


def migrate_panel_routing(bind) -> None:
    t = _tables()
    template = bind.execute(
        sa.select(t["templates"].c.id).where(t["templates"].c.group_id.is_(None), t["templates"].c.template_type == "integration_alert")
    ).first()
    email_rows = []
    if template is not None:
        es = t["email_subs"]
        email_rows = bind.execute(
            sa.select(es.c.id, es.c.group_id, es.c.enabled).where(
                es.c.event_type == NEEDED, es.c.template_id == template.id, es.c.recipient_type == "admins"
            )
        ).all()
    isubs = t["integration_subs"]
    chat_rows = [
        row
        for row in bind.execute(
            sa.select(isubs.c.id, isubs.c.group_id, isubs.c.integration_id, isubs.c.action, isubs.c.args, isubs.c.enabled).where(
                isubs.c.event_type == NEEDED
            )
        ).all()
        if panel_args(row.args)
    ]

    groups = {str(g) for (g,) in bind.execute(sa.select(t["integrations"].c.group_id).distinct()).all()}
    groups |= {str(r.group_id) for r in email_rows} | {str(r.group_id) for r in chat_rows}
    prefs = t["prefs"]
    for group in sorted(groups):
        email_ids = {str(r.id) for r in email_rows if str(r.group_id) == group}
        email_on = any(r.enabled for r in email_rows if str(r.group_id) == group)
        route_for: dict[str, str] = {}
        routes = []
        for row in (r for r in chat_rows if str(r.group_id) == group):
            route_id = str(uuid.uuid4())
            route_for[str(row.id)] = route_id
            routes.append(
                {
                    "id": route_id,
                    "integration_id": str(row.integration_id),
                    "action": row.action,
                    "args": {},
                    "enabled": bool(row.enabled),
                    "kinds": [INTEGRATION_KIND],
                }
            )
        group_id = uuid.UUID(group)
        bind.execute(
            prefs.update()
            .where(prefs.c.group_id == group_id, prefs.c.notifications_json.is_(None))
            .values(notifications_json=settings_for(email_on, routes))
        )
        alerts = t["alerts"]
        for alert in bind.execute(sa.select(alerts.c.id, alerts.c.channels).where(alerts.c.group_id == group_id, alerts.c.status == "open")).all():
            bind.execute(alerts.update().where(alerts.c.id == alert.id).values(channels=rewrite_channels(alert.channels, email_ids, route_for)))

    if email_rows:
        es = t["email_subs"]
        bind.execute(es.delete().where(es.c.id.in_([r.id for r in email_rows])))
    if chat_rows:
        bind.execute(isubs.delete().where(isubs.c.id.in_([r.id for r in chat_rows])))


def upgrade() -> None:
    op.create_table(
        "workspace_alert_incidents",
        sa.Column("id", mt.GUID(), nullable=False),
        sa.Column("group_id", mt.GUID(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channels", sa.JSON(), nullable=True),
        sa.Column("created_at", mt.NaiveDateTime(), nullable=True),
        sa.Column("update_at", mt.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "key", name="uq_workspace_alert_incidents_key"),
    )
    with op.batch_alter_table("workspace_alert_incidents", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workspace_alert_incidents_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_workspace_alert_incidents_group_id"), ["group_id"], unique=False)

    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("notifications_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("notifications_status_json", sa.JSON(), nullable=True))

    migrate_panel_routing(op.get_bind())


def downgrade() -> None:
    with op.batch_alter_table("group_preferences", schema=None) as batch_op:
        batch_op.drop_column("notifications_status_json")
        batch_op.drop_column("notifications_json")

    with op.batch_alter_table("workspace_alert_incidents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workspace_alert_incidents_group_id"))
        batch_op.drop_index(batch_op.f("ix_workspace_alert_incidents_created_at"))

    op.drop_table("workspace_alert_incidents")
