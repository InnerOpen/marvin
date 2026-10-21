"""Delete what a removed integration left behind (Automation Lists 10).

**What "removed" means.** Deleting an integration sets ``source_integration_id`` to NULL on every row it installed (the FK is
ON DELETE SET NULL), so nothing ever points at a missing integration. ``source_blueprint`` survives, and a person's own row has
neither. So an item of a removed integration is one with a blueprint and no integration. The list kit
(frontend/src/lib/organizedList.ts ``sectionKey``) groups by the same rule.

**One guard.** ``installed_by`` also leaves the integration NULL, blueprint set, when it could not tell which connection
installed the row (two connections of one provider). Those items are not removed, and deleting them is destructive, so rows whose
blueprint belongs to a provider the workspace still has a connection for are skipped (and counted). A blueprint the catalog no
longer knows (its plugin is gone) cannot be told apart and counts as removed.

Four kinds, each only in the caller's workspace: workflows (with their backing schedule), incoming webhooks, workspace scheduled
tasks and outgoing webhooks. Collections and event subscriptions are not part of the action. Like the integration's own delete,
nothing is announced on the event bus.
"""

from dataclasses import dataclass, field

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.groups.integrations import IntegrationModel
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
    skipped: int = 0


def _provider_of(blueprint_slug: str) -> str | None:
    """The provider whose blueprint this is, or None (a core blueprint, or one whose plugin is not installed)."""
    from marvin.services.blueprints.catalog import list_blueprints

    for blueprint in list_blueprints():
        if blueprint.slug == blueprint_slug:
            return blueprint.source
    return None


def delete_removed(session, group_id, kind: str) -> Outcome:
    model = MODELS[kind]
    rows = (
        session.query(model)
        .filter(model.group_id == group_id, model.source_integration_id.is_(None), model.source_blueprint.isnot(None))
        .order_by(model.name)
        .all()
    )
    providers = {p for (p,) in session.query(IntegrationModel.provider).filter(IntegrationModel.group_id == group_id)}
    outcome = Outcome()
    for row in rows:
        if _provider_of(row.source_blueprint) in providers:
            outcome.skipped += 1
            continue
        outcome.names.append(row.name)
        if kind == "workflows":
            delete_workflow(session, group_id, row)  # also its schedule task; commits
        else:
            session.delete(row)
    session.commit()
    return outcome
