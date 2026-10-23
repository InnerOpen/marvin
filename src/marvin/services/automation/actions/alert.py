"""`alert` step — send the workspace an alert. No AI.

`level` is info (the default), warning or error: the bell's colour (warning and error stay until dismissed, and show
under "failures only"), and a "Warning:" / "Error:" ahead of the title in an email or a chat. `title` and `message` are
what the alert says up front; `details` is the longer part it opens to (the bell's **More**,
under the message in an email or a chat). All three are templates (`${entry.title}`, `{{SLUG}}` Variables); `details`
may be a template to a list or an object (`${steps.check.output.rows}`), shown a line per item.

The step records a `workflow_alert` event. The bell shows it, and Settings → Automation → Notifications sends it where
"Sent by a workflow" alerts go — email to the owners and admins, push, a connected channel such as Slack (each channel's
last delivery shows there). `link` (optional) is a page in the admin (`/automation/approvals`) or a web address; the
default is the workflow's runs. `idempotency_key` (a template, e.g. `low-stock-${entry.id}`) sends once: the same key from this
workflow within `idempotency_window_hours` (default 24, at most 720) sends nothing (services/automation/idempotency.py).
A dry run renders the alert and lists where it would go, and sends nothing.
"""

from __future__ import annotations

import json

from ..matcher import interpolate
from .base import AutomationActionError, register_action

LEVELS = ("info", "warning", "error")
MAX_TITLE_CHARS = 200
MAX_MESSAGE_CHARS = 1500
MAX_DETAILS_CHARS = 10_000


def _text(action: dict, key: str, context: dict) -> str:
    return str(interpolate(action.get(key) or "", context) or "").strip()


def _details(action: dict, context: dict) -> str:
    """The details as text: a list a line per item, an object a line per key, anything else as it is."""
    value = interpolate(action.get("details"), context)
    if isinstance(value, dict):
        lines = [f"{k}: {v if isinstance(v, str) else json.dumps(v, default=str)}" for k, v in value.items()]
    elif isinstance(value, list):
        lines = [v if isinstance(v, str) else json.dumps(v, default=str) for v in value]
    else:
        lines = [str(value or "").strip()]
    return "\n".join(lines).strip()[:MAX_DETAILS_CHARS]


def _link(action: dict, context: dict) -> str | None:
    """The page the alert opens: the step's `link` (an admin path or an http(s) address); None for the workflow's runs."""
    link = _text(action, "link", context)
    if not link or (link.startswith("/") and not link.startswith("//")) or link.startswith(("http://", "https://")):
        return link or None
    raise AutomationActionError(f"alert step: link must be a page in the admin (/…) or a web address, not {link[:80]!r}", code="bad_link")


def _emit(group_id, context: dict, alert: dict, user_id) -> None:
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventTypes, EventWorkflowAlertData

    step = context.get("_step") or {}
    data = EventWorkflowAlertData(
        automation_id=step.get("automation_id"),
        automation_name=step.get("workflow_name"),
        automation_slug=step.get("workflow_slug"),
        entry_id=(context.get("entry") or {}).get("id"),
        **alert,
    )
    EventBusService(bg_tasks=None).dispatch(
        integration_id="automations",
        group_id=group_id,
        event_type=EventTypes.workflow_alert,
        document_data=data,
        message=f"{alert['title']} — {alert['message']}" if alert["message"] else alert["title"],
        user_id=user_id,
        entity_id=step.get("automation_id"),
        entity_type="automation",
    )


@register_action("alert")
def run_alert(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from marvin.services import workspace_alerts

    from .. import idempotency
    from ..authz import ALERT_MIN_ROLE, ROLE_OWNER, require_role

    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, ALERT_MIN_ROLE, "alert step")
    title = " ".join(_text(action, "title", context).split())[:MAX_TITLE_CHARS]
    if not title:
        raise AutomationActionError("alert step: the title came out empty", code="empty_title")
    alert = {
        "title": title,
        "level": action.get("level") if action.get("level") in LEVELS else "info",
        "message": _text(action, "message", context)[:MAX_MESSAGE_CHARS] or None,
        "details": _details(action, context) or None,
        "link": _link(action, context),
    }
    channels = workspace_alerts.channels_for(session, group_id, workspace_alerts.WORKFLOW_ALERT)
    gate = idempotency.open_gate(session, group_id, action, context, destination="alert", dry_run=dry_run)
    preview = {"dry_run": True, "kind": "alert", **alert, "channels": channels}
    if gate is not None and gate.duplicate:  # sent once already for this key: nothing goes
        return gate.skipped(preview if dry_run else None)
    if dry_run:
        return {**preview, **(gate.preview() if gate else {})}
    try:
        _emit(group_id, context, alert, user_id)
    except Exception:
        if gate is not None:
            gate.release()
        raise
    out = {"sent": True, "title": title, "channels": channels}
    if gate is not None:
        gate.complete(out)
    return out
