"""Delete what a removed integration left behind (Automation Lists 10).

**What "removed" means.** Deleting an integration sets ``source_integration_id`` to NULL on every row it installed (the FK is
ON DELETE SET NULL), so nothing ever points at a missing integration. ``source_blueprint`` survives, and a person's own row has
neither. So an item of a removed integration is one with a blueprint and no integration. The list kit
(frontend/src/lib/organizedList.ts ``sectionKey``) groups by the same rule, and this deletes exactly what that section lists:
the person confirmed those items by name, so nothing is second-guessed here. (A sibling connection of the same provider
staying behind is the usual case — a sandbox replaced by production — not a reason to keep its leftovers.)

Four kinds, each only in the caller's workspace: workflows (with their backing schedule), incoming webhooks, workspace scheduled
tasks and outgoing webhooks. Collections and event subscriptions are not part of the action. Like the integration's own delete,
nothing is announced on the event bus.
"""

from dataclasses import dataclass, field

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
    rows = (
        session.query(model)
        .filter(model.group_id == group_id, model.source_integration_id.is_(None), model.source_blueprint.isnot(None))
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
