"""Executor for the ``approval`` step: wait for a person (services/automation/approvals.py).

It doesn't wait itself: it resolves the message and hands the engine a park request (``PARK``), and the engine parks
the run there — recorded, the run ends ``waiting`` — until a decision resumes it from the next step. A dry run shows
what would be asked and doesn't wait.
"""

from __future__ import annotations

from ..matcher import interpolate
from .base import AutomationActionError, register_action

PARK = "_park"  # the key a park request comes back under (engine._StepRunner parks on it)


@register_action("approval")
def run_approval_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    message = str(interpolate(action.get("message") or "", context) or "").strip()
    if not message:
        raise AutomationActionError("an approval step needs a message: what the approvers are asked")
    approvers = action.get("approvers") or "editor"
    hours = int(action.get("expires_in_hours") or 72)
    if dry_run:
        context["_approval_ahead"] = True  # the preview goes on as if approved, so the steps it guards show too
        return {"dry_run": True, "kind": "approval", "message": message, "approvers": approvers, "expires_in_hours": hours, "would_wait": True}
    return {PARK: {"message": message, "approvers": approvers, "expires_in_hours": hours}}
