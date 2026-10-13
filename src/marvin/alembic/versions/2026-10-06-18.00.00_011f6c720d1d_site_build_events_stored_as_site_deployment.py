"""site_build_* events: stored as their site_deployment_* counterparts

`site_build_started/completed/failed` and `site_deployment_*` were two families for one thing (a host reporting a
build or deploy). The deployment family is kept; the build names became aliases (`CatalogEntry.alias_of`), and the
models now store an alias as the event it stands for. This rewrites what was stored before that:

* workflow triggers (`workspace_automations.trigger_event` of an "event" trigger),
* Emit event steps in a workflow's actions and on-failure steps (`workspace_automations.definition`),
* webhook, email and integration subscriptions (`event_type`). A webhook already subscribed to the counterpart
  keeps that row and drops the alias row (one row per webhook and event).

Production has none of these; a dev or other install may. Idempotent: a second run finds nothing to change.
Downgrade leaves the rows as they are: the deployment names were always valid, so the old code runs them the same.
The alias map is copied here on purpose: a migration must not change meaning when the catalog moves on.

Revision ID: 011f6c720d1d
Revises: 5b0e7d2c9a41
Create Date: 2026-10-06 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt

# revision identifiers, used by Alembic.
revision: str = "011f6c720d1d"
down_revision: str | None = "5b0e7d2c9a41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALIASES = {f"site_build_{s}": f"site_deployment_{s}" for s in ("started", "completed", "failed")}


def _steps(body):
    """The definition with each Emit event step's alias replaced; None when nothing changes."""
    if not isinstance(body, dict):
        return None
    out, changed = dict(body), False
    for key in ("actions", "on_failure"):
        steps = body.get(key)
        if not isinstance(steps, list):
            continue
        fixed = []
        for step in steps:
            if isinstance(step, dict) and step.get("kind") == "emit_event" and step.get("event") in _ALIASES:
                step, changed = {**step, "event": _ALIASES[step["event"]]}, True
            fixed.append(step)
        out[key] = fixed
    return out if changed else None


def upgrade() -> None:
    bind = op.get_bind()

    workflows = sa.table(
        "workspace_automations",
        sa.column("id", mt.GUID()),
        sa.column("definition", sa.JSON()),
        sa.column("trigger_type", sa.String()),
        sa.column("trigger_event", sa.String()),
    )
    for alias, target in _ALIASES.items():
        bind.execute(workflows.update().where(workflows.c.trigger_type == "event", workflows.c.trigger_event == alias).values(trigger_event=target))
    for row in bind.execute(sa.select(workflows.c.id, workflows.c.definition)).all():
        fixed = _steps(row.definition)
        if fixed is not None:
            bind.execute(workflows.update().where(workflows.c.id == row.id).values(definition=fixed))

    webhook_subs = sa.table(
        "webhook_event_subscriptions",
        sa.column("id", mt.GUID()),
        sa.column("webhook_id", mt.GUID()),
        sa.column("event_type", sa.String()),
    )
    for alias, target in _ALIASES.items():
        already = sa.select(webhook_subs.c.webhook_id).where(webhook_subs.c.event_type == target).scalar_subquery()
        bind.execute(webhook_subs.delete().where(webhook_subs.c.event_type == alias, webhook_subs.c.webhook_id.in_(already)))
        bind.execute(webhook_subs.update().where(webhook_subs.c.event_type == alias).values(event_type=target))

    for name in ("email_event_subscriptions", "integration_event_subscriptions"):
        subs = sa.table(name, sa.column("event_type", sa.String()))
        for alias, target in _ALIASES.items():
            bind.execute(subs.update().where(subs.c.event_type == alias).values(event_type=target))
    # Event Log rows are history: they keep the name they were sent with.


def downgrade() -> None:
    pass
