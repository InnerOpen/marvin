"""Delete what a removed integration left behind (Automation Lists 10).

**What "removed" means.** Deleting an integration sets ``source_integration_id`` to NULL on every row it installed (the FK is
ON DELETE SET NULL), so nothing ever points at a missing integration. ``source_blueprint`` survives, and a person's own row has
neither. So an item of a removed integration is one with a blueprint and no integration. The list kit
(frontend/src/lib/organizedList.ts ``sectionKey``) groups by the same rule, and this deletes exactly what that section lists:
the person confirmed those items by name, so nothing is second-guessed here. A row in a **package** (``source_package``) is not one of them,
whatever else it carries: a package installs workflows from a blueprint with no integration behind them, and they are listed under
their package, so this must never reach them. (A sibling connection of the same provider
staying behind is the usual case — a sandbox replaced by production — not a reason to keep its leftovers.)

**The one exception: an incoming webhook.** It is the address the outside service posts to, a workspace has one per blueprint
whichever connection installed it, and deleting it means setting the address up again at the service. So while the workspace has
any connection of the provider whose blueprint made it, the webhook is that connection's and not a removed one's:
``keep_webhooks`` hands it over when its own connection is deleted, when the provider is connected again, and at startup for
the ones orphaned before this rule.

Four kinds, each only in the caller's workspace: workflows (with their backing schedule), incoming webhooks, workspace scheduled
tasks and outgoing webhooks. Collections and event subscriptions are not part of the action. Like the integration's own delete,
nothing is announced on the event bus.
"""

from dataclasses import dataclass, field

import sqlalchemy as sa

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.groups.webhooks import GroupWebhooksModel
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services.automation.workflows import delete_workflow

MODELS = {
    "workflows": WorkspaceAutomationModel,
    "incoming-webhooks": WorkspaceIncomingWebhookModel,
    "scheduled-tasks": ScheduledTaskModel,
    "outgoing-webhooks": GroupWebhooksModel,
}


@dataclass
class Outcome:
    names: list[str] = field(default_factory=list)


def delete_removed(session, group_id, kind: str) -> Outcome:
    model = MODELS[kind]
    packaged = getattr(model, "source_package", None)  # not every kind can be in a package (outgoing webhooks cannot)
    rows = (
        session.query(model)
        .filter(
            model.group_id == group_id,
            model.source_integration_id.is_(None),
            model.source_blueprint.isnot(None),
            *([packaged.is_(None)] if packaged is not None else []),
        )
        .order_by(model.name)
        .all()
    )
    outcome = Outcome()
    for row in rows:
        outcome.names.append(row.name)
        if kind == "workflows":
            delete_workflow(session, group_id, row)  # also its schedule task; commits
        else:
            session.delete(row)
    session.commit()
    return outcome


def _webhook_providers() -> dict[str, str]:
    """Which provider ships each incoming-webhook blueprint, by the blueprint's slug. A slug two providers both use says nothing."""
    from marvin.schemas.platform.blueprints import CORE_SOURCE
    from marvin.services.blueprints.catalog import list_blueprints

    found: dict[str, str | None] = {}
    for blueprint in list_blueprints(kind="incoming_webhook"):
        if blueprint.source != CORE_SOURCE:
            found[blueprint.slug] = blueprint.source if blueprint.slug not in found else None
    return {slug: provider for slug, provider in found.items() if provider}


def _home(session, group_id, provider: str):
    """The connection of this provider a webhook goes to, or None when the workspace has none: one that is switched on before one
    that is off, then the one with the most workflows installed (the webhook is what starts them), then the oldest."""
    from marvin.db.models.groups.integrations import IntegrationModel

    workflows = (
        sa.select(sa.func.count())
        .where(WorkspaceAutomationModel.source_integration_id == IntegrationModel.id)
        .correlate(IntegrationModel)
        .scalar_subquery()
    )
    row = (
        session.query(IntegrationModel.id)
        .filter_by(group_id=group_id, provider=provider)
        .order_by(IntegrationModel.enabled.desc(), workflows.desc(), IntegrationModel.created_at, IntegrationModel.id)
        .first()
    )
    return row[0] if row else None


def keep_webhooks(session, group_id=None) -> int:
    """Hand each incoming webhook a deleted connection left behind to a connection of the same provider still in its workspace
    (``_home`` says which), so it stops being listed as a removed integration's. In one workspace, or in all of them. Returns how
    many moved; a webhook whose provider has no connection left stays a removed one."""
    orphans = session.query(WorkspaceIncomingWebhookModel).filter(
        WorkspaceIncomingWebhookModel.source_integration_id.is_(None),
        WorkspaceIncomingWebhookModel.source_blueprint.isnot(None),
        WorkspaceIncomingWebhookModel.source_package.is_(None),
    )
    if group_id is not None:
        orphans = orphans.filter(WorkspaceIncomingWebhookModel.group_id == group_id)
    rows = orphans.all()
    if not rows:
        return 0
    providers = _webhook_providers()
    moved = 0
    for row in rows:
        provider = providers.get(row.source_blueprint)
        if provider is None:
            continue
        home = _home(session, row.group_id, provider)
        if home is not None:
            row.source_integration_id = home
            moved += 1
    if moved:
        session.commit()
    return moved
