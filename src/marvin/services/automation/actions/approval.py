"""Executor for the ``approval`` step: wait for a person (services/automation/approvals.py).

It doesn't wait itself: it resolves the message and hands the engine a park request (``PARK``), and the engine parks
the run there — recorded, the run ends ``waiting`` — until a decision resumes it from the next step. A dry run shows
what would be asked and doesn't wait.
"""

from __future__ import annotations

from ..matcher import interpolate
from .base import AutomationActionError, register_action

PARK = "_park"  # the key a park request comes back under (engine._StepRunner parks on it)
MAX_CHOICES = 8
MAX_LABEL = 200


@register_action("approval")
def run_approval_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    message = str(interpolate(action.get("message") or "", context) or "").strip()
    if not message:
        raise AutomationActionError("an approval step needs a message: what the approvers are asked")
    approvers = action.get("approvers") or "editor"
    hours = int(action.get("expires_in_hours") or 72)
    choices = _choices(action.get("choices"), context)
    if dry_run:
        context["_approval_ahead"] = True  # the preview goes on as if approved, so the steps it guards show too
        out = {"dry_run": True, "kind": "approval", "message": message, "approvers": approvers, "expires_in_hours": hours, "would_wait": True}
        return {**out, "choices": choices} if choices else out
    spec = {"message": message, "approvers": approvers, "expires_in_hours": hours}
    return {PARK: {**spec, "choices": choices} if choices else spec}


def _choices(raw, context: dict) -> list[str] | None:
    """The labels to pick from: each a template, or one template to a list. None when the step offers none; an
    error when it meant to and they resolved to fewer than two (or more than MAX_CHOICES)."""
    if raw in (None, "", []):
        return None
    resolved = interpolate(raw, context)
    items = resolved if isinstance(resolved, list) else [resolved]
    labels = [str(x).strip()[:MAX_LABEL] for x in items if x not in (None, "") and str(x).strip()]
    if len(labels) < 2:
        raise AutomationActionError(f"an approval's choices resolved to {len(labels)}: it needs at least two to pick from")
    if len(labels) > MAX_CHOICES:
        raise AutomationActionError(f"an approval offers at most {MAX_CHOICES} choices, not {len(labels)}")
    return labels
