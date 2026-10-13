"""migrate event notifiers to apprise integrations

Additive, reversible step of extracting Apprise into an integration plugin. For each
``group_events_notifier`` it creates:
  - a workspace secret holding the Apprise URL (Fernet-encrypted, same key the DB backend uses),
  - an ``apprise`` integration referencing that secret,
  - an integration event subscription (action ``notify``) for each explicitly-subscribed event.

Core Apprise is left running (coexistence) — this only mirrors the config onto the integration model
so the notifier tables can be dropped and the core code removed in a following step. A notifier with
no explicit event options migrates the connection but no subscriptions (re-select events in the UI);
we don't fan a "default = all events" notifier out to every event.

Revision ID: e49ab4346b7b
Revises: 1467f4e1c2f7
Create Date: 2026-07-25 22:04:16.962866

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

revision: str = "e49ab4346b7b"
down_revision: str | None = "1467f4e1c2f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Args template for the migrated `notify` subscription. The integration event context exposes the raw
# event fields (event_type, message, document data) — not the notifier's old auto-composed title.
_NOTIFY_ARGS = {"title": "Marvin: {{event_type}}", "body": "{{message}}"}


def _notifiers():
    return sa.table(
        "group_events_notifiers",
        sa.column("id", mt.GUID()),
        sa.column("name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("apprise_url", sa.String()),
        sa.column("group_id", mt.GUID()),
    )


def _notifier_options():
    return sa.table(
        "group_events_notifier_options",
        sa.column("slug", sa.String()),
        sa.column("group_event_notifiers_id", mt.GUID()),
    )


def _integrations():
    return sa.table(
        "integrations",
        sa.column("id", mt.GUID()),
        sa.column("group_id", mt.GUID()),
        sa.column("provider", sa.String()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("secret_ref", sa.String()),
        sa.column("status", sa.String()),
    )


def _subscriptions():
    return sa.table(
        "integration_event_subscriptions",
        sa.column("id", mt.GUID()),
        sa.column("group_id", mt.GUID()),
        sa.column("integration_id", mt.GUID()),
        sa.column("event_type", sa.String()),
        sa.column("action", sa.String()),
        sa.column("args", sa.JSON()),
        sa.column("enabled", sa.Boolean()),
    )


def _secrets():
    return sa.table(
        "workspace_secrets",
        sa.column("id", mt.GUID()),
        sa.column("group_id", mt.GUID()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("description", sa.String()),
        sa.column("encrypted_value", sa.Text()),
    )


def _hex(u) -> str:
    return u.hex if isinstance(u, uuid.UUID) else str(u).replace("-", "")


def _secret_slug(nid) -> str:
    return f"APPRISE_{_hex(nid).upper()}"


def _integration_slug(nid) -> str:
    return f"apprise-{_hex(nid)}"


def upgrade() -> None:
    from marvin.services.secrets.backends.database import _get_fernet

    bind = op.get_bind()
    notifiers, notifier_opts = _notifiers(), _notifier_options()
    integrations, subs, secrets = _integrations(), _subscriptions(), _secrets()

    for n in bind.execute(sa.select(notifiers)).fetchall():
        if n.group_id is None or not n.apprise_url:
            continue
        secret_slug = _secret_slug(n.id)
        bind.execute(
            secrets.insert().values(
                id=uuid.uuid4(),
                group_id=n.group_id,
                name=f"Apprise: {n.name}",
                slug=secret_slug,
                description="Migrated from an event notifier.",
                encrypted_value=_get_fernet().encrypt(n.apprise_url.encode()).decode(),
            )
        )
        integ_id = uuid.uuid4()
        bind.execute(
            integrations.insert().values(
                id=integ_id,
                group_id=n.group_id,
                provider="apprise",
                name=n.name,
                slug=_integration_slug(n.id),
                enabled=bool(n.enabled),
                secret_ref=secret_slug,
                status="unconfigured",
            )
        )
        events = [r.slug for r in bind.execute(sa.select(notifier_opts.c.slug).where(notifier_opts.c.group_event_notifiers_id == n.id))]
        for event_type in events:
            bind.execute(
                subs.insert().values(
                    id=uuid.uuid4(),
                    group_id=n.group_id,
                    integration_id=integ_id,
                    event_type=event_type,
                    action="notify",
                    args=dict(_NOTIFY_ARGS),
                    enabled=True,
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    notifiers = _notifiers()
    integrations, subs, secrets = _integrations(), _subscriptions(), _secrets()

    # The notifier rows still exist in this additive step, so recompute the deterministic slugs and
    # delete exactly what upgrade() created (its integrations, their subscriptions, and the secrets).
    for n in bind.execute(sa.select(notifiers)).fetchall():
        integ = bind.execute(
            sa.select(integrations.c.id).where(integrations.c.group_id == n.group_id, integrations.c.slug == _integration_slug(n.id))
        ).first()
        if integ is not None:
            bind.execute(subs.delete().where(subs.c.integration_id == integ.id))
            bind.execute(integrations.delete().where(integrations.c.id == integ.id))
        bind.execute(secrets.delete().where(secrets.c.group_id == n.group_id, secrets.c.slug == _secret_slug(n.id)))
