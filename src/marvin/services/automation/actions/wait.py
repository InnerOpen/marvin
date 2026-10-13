"""Executor for the ``wait`` step: go on later (services/automation/waits.py).

Like the approval step it doesn't wait itself: it works out when, and hands the engine a park request (``PARK``) — the
run is recorded ``waiting`` and the minutely sweep resumes it then. A moment already past goes on at once (``late``);
a dry run shows when it would go on and doesn't wait.
"""

from __future__ import annotations

from ..matcher import interpolate
from .approval import PARK
from .base import register_action

SOON = 60  # seconds: a wait shorter than the sweep's tick goes on at once


@register_action("wait")
def run_wait_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from .. import waits

    when = waits.resume_time(
        session,
        group_id,
        wait_for=interpolate(action.get("for"), context),
        until=interpolate(action.get("until"), context),
        offset=interpolate(action.get("offset"), context),
        at=interpolate(action.get("at"), context),
    )
    current = waits.now()
    waits.check_reach(when, current)
    if (when - current).total_seconds() <= SOON:  # already past (or nearly): no waiting
        return {"waited_until": when.isoformat(), "late": when < current, "waited": False}
    if dry_run:
        return {"dry_run": True, "kind": "wait", "would_wait_until": when.isoformat(), "late": False}
    return {PARK: {"kind": "wait", "resume_at": when}}
