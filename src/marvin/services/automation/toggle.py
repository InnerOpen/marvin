"""Switch an automation on or off — one path for the admin pages, the API and the agent's
`set_automation_enabled` tool, so every switch is audited the same way.

Two kinds, with the ids the event graph (`services/events/connections.py`, the agent's `describe_event`) uses:

- ``integration_action``: an event → action connection (`integration_event_subscriptions`). It runs only while
  its integration is switched on too, so the result says whether it is *effectively* on; switching the
  integration itself is a bigger change and never happens here.
- ``workflow``: a workspace automation (`workspace_automations`), through `update_workflow`, which also keeps a
  schedule trigger's backing task in step.

Only `enabled` changes: never args, definitions, triggers or credentials. Switching to the state it is already
in writes nothing and sends nothing. Each real change sends `<kind>_enabled` / `<kind>_disabled`
(`automation_*` for workflows), which the event log always keeps.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from marvin.services.event_bus_service.event_types import EventAutomationToggledData, EventTypes

INTEGRATION_ACTION = "integration_action"
WORKFLOW = "workflow"
KINDS = (INTEGRATION_ACTION, WORKFLOW)
VIA_UI = "ui"
VIA_AGENT = "agent"
MAX_REASON = 200

_EVENTS = {
    (INTEGRATION_ACTION, True): EventTypes.integration_action_enabled,
    (INTEGRATION_ACTION, False): EventTypes.integration_action_disabled,
    (WORKFLOW, True): EventTypes.automation_enabled,
    (WORKFLOW, False): EventTypes.automation_disabled,
}


@dataclass
class Automation:
    """One switchable automation, described for an approval card and the audit event."""

    kind: str
    row: Any
    name: str
    enabled: bool
    reacts_to: str | None
    does: str
    """In plain words, what it does when it runs."""
    source_blueprint: str | None
    parent_name: str | None = None
    parent_enabled: bool | None = None
    """An integration action's integration: it must be on too. None for a workflow."""
    agent_draft: bool = False

    def effective(self, enabled: bool) -> bool:
        return enabled and self.parent_enabled is not False

    def warning(self, enabled: bool) -> str | None:
        """Why it still won't run once switched to `enabled`, if it won't."""
        if enabled and self.parent_enabled is False:
            return f"The {self.parent_name} integration is switched off, so this still won't run until someone switches the integration on."
        return None


def find(session, group_id, kind: str, automation_id) -> Automation | None:
    """The automation in this workspace, or None — another workspace's id is simply not found."""
    try:
        key = automation_id if isinstance(automation_id, uuid.UUID) else uuid.UUID(str(automation_id))
    except ValueError:
        return None
    if kind == INTEGRATION_ACTION:
        return _integration_action(session, group_id, key)
    if kind == WORKFLOW:
        return _workflow(session, group_id, key)
    return None


def _integration_action(session, group_id, key) -> Automation | None:
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel

    row = session.get(IntegrationEventSubscriptionModel, key)
    if row is None or row.group_id != group_id:
        return None
    integration = row.integration
    integration_name = integration.name if integration else "its"
    text = (row.args or {}).get("text") or (row.args or {}).get("message")
    does = f"runs {integration_name} → {row.action} on every {row.event_type}"
    if text:
        does += f" (message: “{text}”)"
    return Automation(
        kind=INTEGRATION_ACTION,
        row=row,
        name=f"{integration_name} → {row.action}",
        enabled=bool(row.enabled),
        reacts_to=row.event_type,
        does=does,
        source_blueprint=row.source_blueprint,
        parent_name=integration_name,
        parent_enabled=bool(integration.enabled) if integration else False,
    )


def _workflow(session, group_id, key) -> Automation | None:
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    row = session.get(WorkspaceAutomationModel, key)
    if row is None or row.group_id != group_id:
        return None
    reacts_to = row.trigger_event or row.trigger_type
    steps = len((row.body or {}).get("actions") or [])
    does = f"runs the workflow “{row.name}”" + (f" ({steps} step{'s' if steps != 1 else ''})" if steps else "")
    if reacts_to:
        does += f" on {reacts_to}"
    return Automation(
        kind=WORKFLOW,
        row=row,
        name=row.name,
        enabled=bool(row.enabled),
        reacts_to=reacts_to,
        does=does,
        source_blueprint=row.source_blueprint,
        agent_draft=bool(row.agent_draft),
    )


def set_enabled(
    session, group_id, target: Automation, enabled: bool, *, actor_id=None, via: str = VIA_UI, reason: str | None = None, event_bus=None
) -> bool:
    """Switch it; False (nothing written, nothing sent) when it was already in that state."""
    if target.enabled == enabled:
        return False
    if target.kind == WORKFLOW:
        from marvin.schemas.group.automation import AutomationUpdate
        from marvin.services.automation.workflows import update_workflow

        update_workflow(session, group_id, target.row, AutomationUpdate(enabled=enabled))
    else:
        target.row.enabled = enabled
        session.commit()
    target.enabled = enabled
    _audit(group_id, target, enabled, actor_id=actor_id, via=via, reason=reason, event_bus=event_bus)
    return True


def record_switch(session, group_id, kind: str, automation_id, *, actor_id=None, via: str = VIA_UI, event_bus=None) -> None:
    """Audit a switch an update already made (a PATCH that changed `enabled` with other fields)."""
    target = find(session, group_id, kind, automation_id)
    if target is not None:
        _audit(group_id, target, target.enabled, actor_id=actor_id, via=via, reason=None, event_bus=event_bus)


def _audit(group_id, target: Automation, enabled: bool, *, actor_id, via, reason, event_bus) -> None:
    if event_bus is None:
        from marvin.services.event_bus_service.event_bus_service import EventBusService

        event_bus = EventBusService(bg_tasks=None)  # synchronous fan-out, like the Trash
    reason = (reason or "").strip()[:MAX_REASON] or None
    event_bus.dispatch(
        integration_id="automation_toggle",
        group_id=group_id,
        event_type=_EVENTS[(target.kind, enabled)],
        document_data=EventAutomationToggledData(
            kind=target.kind,
            automation_id=target.row.id,
            name=target.name,
            enabled=enabled,
            effective=target.effective(enabled),
            reacts_to=target.reacts_to,
            source_blueprint=target.source_blueprint,
            via=via,
            reason=reason,
            workspace_id=group_id,
        ),
        message=f"{'Switched on' if enabled else 'Switched off'}: {target.name}" + (f" ({reason})" if reason else ""),
        user_id=actor_id,
        entity_id=target.row.id,
        entity_type=target.kind,
    )
