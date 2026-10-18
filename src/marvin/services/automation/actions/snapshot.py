"""`snapshot` step — capture a version of an entry, and restore it later (services/snapshots.py).

**capture** (the default `op`): keeps what the entry is now — title, summary, description, data, metadata, status, its
collections and attached assets (references) — and outputs `snapshot_id` (for a later `restore` step in this workflow, or
another run), `label`, `created` and what it holds. `label` names it ("before the refresh"). An entry whose latest snapshot is
already identical gets that one back (`created: false`), so a run repeated for the same entry adds nothing; an entry keeps its
latest 20 snapshots. A dry run says what it would do (`would`: capture | reuse) and keeps nothing.

**restore**: puts a snapshot back on its entry. `snapshot` is a snapshot id (usually `${steps.<id>.output.snapshot_id}`); left
out, the entry's latest snapshot (with `label`, when given) is used. `parts` says what comes back — `content` (title, summary,
description, data, metadata), `collections`, `assets`; default those three — and `status` only when asked for: restoring content
never publishes or unpublishes an entry by itself, and a status that would publish goes through the publish gate. It runs through
the entry service, so the normal events go out (entry_updated, collection and asset-link events, a status transition's own) and
chained workflows see them. Output: `restored`, what `changed` by part, `snapshot_id`. A restore that would change nothing
writes nothing. A dry run previews the same diff (`would`: restore | leave) and writes nothing.

Both need the workflow author's role to be AUTHOR or above, like any entry step. Tags and resource links are not captured.
"""

from __future__ import annotations

from marvin.services import snapshots

from ..matcher import interpolate
from .base import AutomationActionError, register_action
from .entry import _resolve_target


@register_action("snapshot")
def run_snapshot_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from ..authz import ROLE_OWNER, SNAPSHOT_MIN_ROLE, require_role

    op = action.get("op") or "capture"
    if op not in ("capture", "restore"):
        raise AutomationActionError(f"unknown snapshot op '{op}' (expected: capture, restore)")
    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, SNAPSHOT_MIN_ROLE, f"snapshot {op}")
    try:
        if op == "capture":
            return _capture(session, group_id, action, context, user_id, dry_run)
        return _restore(session, group_id, action, context, user_id, dry_run)
    except snapshots.SnapshotError as e:
        raise AutomationActionError(f"snapshot {op}: {e}") from e


def _label(action: dict, context: dict) -> str:
    return snapshots.clean_label(interpolate(action.get("label"), context) if action.get("label") is not None else "")


def _capture(session, group_id, action: dict, context: dict, user_id, dry_run: bool) -> dict:
    entry_id = _resolve_target(session, group_id, action, context)
    label = _label(action, context)
    if dry_run:
        entry = snapshots._entry(session, group_id, entry_id)
        if entry is None:
            raise AutomationActionError(f"entry {entry_id} not found in this workspace")
        newest = snapshots.latest(session, group_id, entry.id)
        same = newest is not None and newest.snapshot_json == snapshots.take(session, entry)
        return {"dry_run": True, "would": "reuse" if same else "capture", "entry_id": str(entry.id), "label": label, "snapshot_id": None}
    row, created = snapshots.capture(
        session, group_id, entry_id, label=label, user_id=user_id, automation_id=_workflow_id(session, context.get("_step") or {}), source="workflow"
    )
    return {"snapshot_id": str(row.id), "created": created, **{k: v for k, v in snapshots.describe(row).items() if k != "id"}}


def _restore(session, group_id, action: dict, context: dict, user_id, dry_run: bool) -> dict:
    parts = snapshots.clean_parts(action.get("parts"))
    ref = interpolate(action["snapshot"], context) if action.get("snapshot") else None
    if action.get("snapshot") and ref in (None, ""):
        if dry_run:  # the capture step before it only previewed: there is no snapshot yet to diff
            return {"dry_run": True, "would": "restore", "snapshot_id": None, "parts": list(parts), "note": "the snapshot an earlier step takes"}
        raise AutomationActionError("snapshot restore: `snapshot` resolved to empty — an earlier capture step gives it")
    explicit = any(action.get(k) for k in ("entity_id", "entity_slug", "entity_query"))
    if ref:
        row = snapshots.get(session, group_id, ref)
        if row is None:
            raise AutomationActionError("snapshot restore: no such snapshot in this workspace")
        if explicit and str(_resolve_target(session, group_id, action, context)) != str(row.entry_id):
            raise AutomationActionError("snapshot restore: that snapshot is of another entry")
    else:
        entry_id = _resolve_target(session, group_id, action, context)
        row = snapshots.latest(session, group_id, entry_id, _label(action, context) or None)
        if row is None:
            raise AutomationActionError("snapshot restore: the entry has no snapshot" + (" with that label" if action.get("label") else ""))
    if dry_run:
        done = snapshots.public(snapshots.plan(session, group_id, row, parts))
        return {"dry_run": True, "would": "restore" if done["changed"] else "leave", **done}
    depth = int(context.get("depth", 0)) + 1
    done = snapshots.restore(session, group_id, row, parts, actor_id=user_id, depth=depth, integration_id="automation")
    return {**done, "snapshot_label": row.label}


def _workflow_id(session, step: dict):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    automation_id = step.get("automation_id")
    return automation_id if automation_id is not None and session.get(WorkspaceAutomationModel, automation_id) is not None else None
