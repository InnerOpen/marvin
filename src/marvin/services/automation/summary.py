"""What a workflow run did and what started it, worded for its automation_ran / automation_failed event.

The event log and the activity toast show an event's message, so a run's message names its steps:
"Automation 'send-issue' ran — webhook 'Buttondown: send issue' → 201". The same steps go into the
event's data (``steps``) for anything that wants them structured.
"""

from typing import Any
from urllib.parse import urlparse
from uuid import UUID

MAX_LISTED_STEPS = 3  # steps named in the message; the rest are counted
MAX_ERROR_CHARS = 200  # a failed step's error as the message quotes it
MAX_STORED_ERROR_CHARS = 500  # …and as the event's data keeps it (the run history has the rest)

# A trigger's own name, by the event field that carries it — the label a run shows next to its link.
_TRIGGER_LABEL_KEYS = ("entry_title", "webhook_name", "automation_name", "collection_name", "form_name", "filename", "name", "title")


def _webhook_name(session, webhook_id) -> str | None:
    from marvin.db.models.groups.webhooks import GroupWebhooksModel

    try:
        webhook = session.get(GroupWebhooksModel, webhook_id)
    except Exception:  # noqa: BLE001 — a name is a nicety; the id still identifies the step
        return None
    name = getattr(webhook, "name", None)
    return name if isinstance(name, str) and name else None


def _target(session, action: dict) -> str | None:
    """What a step acted on, by name where one is known."""
    kind = action.get("kind")
    if kind == "webhook":
        if action.get("webhook_id"):
            return _webhook_name(session, action["webhook_id"]) or str(action["webhook_id"])
        url = str(action.get("url") or "")
        return urlparse(url).netloc or url or None
    if kind in ("operation", "entry"):
        return action.get("op")
    if kind == "emit_event":
        return action.get("event")
    if kind == "handler":
        return action.get("task")
    if kind == "integration":
        return f"{action.get('integration')}.{action.get('action')}"
    return None


def step_summary(session, action: dict, *, output: Any = None, error: str | None = None) -> dict:
    """One step's line: its kind, what it acted on, and how it went (an HTTP status when it made a call)."""
    if error is not None:
        outcome = "failed"
    else:
        status = output.get("status_code") if isinstance(output, dict) else None
        outcome = str(status) if status is not None else "ok"
    return {
        "kind": action.get("kind") or "step",
        "target": _target(session, action),
        "outcome": outcome,
        "ok": error is None,
        "error": error[:MAX_STORED_ERROR_CHARS] if error is not None else None,
        "count": 1,
    }


def collapse(steps: list[dict]) -> list[dict]:
    """A target query runs the same steps once per row; one line per distinct step and outcome, counted."""
    seen: dict[tuple, dict] = {}
    for step in steps:
        key = (step["kind"], step["target"], step["outcome"], step.get("error"))
        if key in seen:
            seen[key]["count"] += 1
        else:
            seen[key] = dict(step)
    return list(seen.values())


def _describe(step: dict) -> str:
    target = f" '{step['target']}'" if step.get("target") else ""
    times = f" ×{step['count']}" if step.get("count", 1) > 1 else ""
    return f"{step['kind']}{target} → {step['outcome']}{times}"


def run_message(slug: str, ok: bool, steps: list[dict]) -> str:
    """The run's event message: its steps on success, the failing step and its error on failure."""
    if not ok:
        failed = next((s for s in reversed(steps) if not s.get("ok")), None)
        if failed is None:
            return f"Automation '{slug}' failed"
        error = str(failed.get("error") or "").strip()
        if len(error) > MAX_ERROR_CHARS:
            error = error[: MAX_ERROR_CHARS - 1] + "…"
        target = f" '{failed['target']}'" if failed.get("target") else ""
        return (
            f"Automation '{slug}' failed — {failed['kind']}{target}: {error}" if error else f"Automation '{slug}' failed — {failed['kind']}{target}"
        )
    if not steps:
        return f"Automation '{slug}' ran — no steps"
    listed = "; ".join(_describe(s) for s in steps[:MAX_LISTED_STEPS])
    more = len(steps) - MAX_LISTED_STEPS
    if more > 0:
        listed += f"; +{more} more step{'s' if more > 1 else ''}"
    return f"Automation '{slug}' ran — {listed}"


def _uuid(value) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def trigger_ref(context: dict) -> dict:
    """The triggering event's subject as automation event fields (all None for a manual/scheduled run)."""
    event = context.get("event") or {}
    entity_id = _uuid(event.get("entity_id"))
    entity_type = event.get("entity_type") if entity_id else None
    if entity_id is None:
        return {"trigger_entity_type": None, "trigger_entity_id": None, "trigger_entity_label": None}
    entry = context.get("entry") if entity_type == "entry" else None
    label = (entry or {}).get("title") or next((event[k] for k in _TRIGGER_LABEL_KEYS if isinstance(event.get(k), str) and event[k]), None)
    return {"trigger_entity_type": entity_type, "trigger_entity_id": entity_id, "trigger_entity_label": label}
