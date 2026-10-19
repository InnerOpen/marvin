"""Approval steps: a workflow run that waits for a person (``{"kind": "approval", …}``).

**Park.** The engine reaches the step (actions/approval.py hands it a park request) and calls ``park``: the run's
snapshot (the event, the entry, the earlier steps' outputs, the target row — what a retry keeps,
services/integrations/errors.py) goes into a ``workflow_approvals`` row with the entry's version, the step is recorded
``waiting``, the run ends ``waiting``, and ``workflow_approval_requested`` tells the approvers (members at the step's
role or above: the push goes to them, Automation → Approvals lists it).

**Decide.** ``decide`` (a member at that role) or ``expire_due`` (the hourly sweep) settles it — approved, denied,
expired — and ``engine.resume_after_approval`` runs the steps after it in a new run (``retry_of`` the parked one), with
``${steps.<id>.output.decision}``. Approving an entry that has changed since it was asked settles it ``stale`` instead:
what the person approved isn't what would be acted on. A run resumed ``approved`` may call integration actions that
require approval (actions/integration.py); nothing else may.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from marvin.db.models.groups.workflow_approvals import APPROVAL_PENDING, WorkflowApprovalModel
from marvin.services.event_bus_service.event_types import EventTypes

from .actions.base import AutomationActionError
from .authz import ROLE_ADMIN, ROLE_EDITOR

ROLE_OF_APPROVERS = {"editor": ROLE_EDITOR, "admin": ROLE_ADMIN}
DECISIONS = {"approve": "approved", "deny": "denied"}
MAX_PENDING_LIST = 100


class ApprovalError(Exception):
    """A decision that can't be taken (the message says why); ``status`` is the HTTP status that fits."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)  # NaiveDateTime stores UTC and reads it back aware


def _entry_version(session, entry_id) -> str | None:
    from marvin.db.models.platform.entries import Entries

    entry = session.get(Entries, entry_id) if entry_id else None
    stamp = getattr(entry, "update_at", None) or getattr(entry, "created_at", None)
    return stamp.isoformat() if stamp else None


def park(session, group_id, automation, context: dict, *, exec_id, step_index: int, target_index: int, step_id, spec: dict, run: dict):
    """Keep the run at this step and tell the approvers. Raises AutomationActionError when it can't wait (an unsaved
    workflow, a run too large to keep)."""
    from marvin.services.integrations.errors import _snapshot

    from .engine import approval_default_hours

    automation_id = getattr(automation, "id", None)
    if automation_id is None:
        raise AutomationActionError("an approval step needs a saved workflow to come back to")
    snapshot = _snapshot(context, run)
    if snapshot is None:
        raise AutomationActionError("this run is too large to wait for an approval")
    entry_id = (context.get("entry") or {}).get("id")  # the entry the run acts on, if any: its version is checked on approval
    row = WorkflowApprovalModel(
        session=session,
        group_id=group_id,
        automation_id=automation_id,
        execution_id=exec_id if exec_id is not None and not isinstance(exec_id, str) else None,
        step_index=step_index,
        step_id=step_id,
        target_index=target_index,
        message=spec["message"],
        min_role=ROLE_OF_APPROVERS.get(spec.get("approvers") or "editor", ROLE_EDITOR),
        status=APPROVAL_PENDING,
        snapshot=snapshot,
        entry_id=entry_id,
        entry_version=_entry_version(session, entry_id),
        expires_at=_now() + timedelta(hours=int(spec.get("expires_in_hours") or approval_default_hours(session, group_id))),
        choices=spec.get("choices") or None,
        image_url=spec.get("image") or None,
    )
    session.add(row)
    session.commit()
    _emit(session, row, automation, EventTypes.workflow_approval_requested, user_id=(context.get("event") or {}).get("user_id"))
    return row


def pending(session, group_id, role: int) -> list[WorkflowApprovalModel]:
    """The approvals waiting in this workspace that a member at `role` may decide, oldest first."""
    return (
        session.query(WorkflowApprovalModel)
        .filter(WorkflowApprovalModel.group_id == group_id, WorkflowApprovalModel.status == APPROVAL_PENDING, WorkflowApprovalModel.min_role <= role)
        .order_by(WorkflowApprovalModel.created_at)
        .limit(MAX_PENDING_LIST)
        .all()
    )


def decide(
    session, group_id, approval_id, decision: str, *, user_id, role: int, note: str | None = None, choice=None, logger=None
) -> WorkflowApprovalModel:
    """A person approves or denies; the run goes on. An approval with choices is approved with one of them (`choice`:
    its label, or its index). Raises ApprovalError (404 unknown, 403 not theirs to decide, 409 already decided or
    expired, 422 no such choice)."""
    row = session.get(WorkflowApprovalModel, approval_id)
    if row is None or str(row.group_id) != str(group_id):
        raise ApprovalError("No such approval.", 404)
    if role < row.min_role:
        raise ApprovalError("This approval needs a member at a higher workspace role.", 403)
    if row.status != APPROVAL_PENDING:
        raise ApprovalError(f"It was already decided: {row.status}.")
    if row.expires_at <= _now():
        raise ApprovalError("It has expired; the workflow goes on as expired.")
    if decision not in DECISIONS:
        raise ApprovalError("Decide approve or deny.", 422)
    outcome = DECISIONS[decision]
    picked = _picked(row, choice) if outcome == "approved" else None
    if outcome == "approved" and row.entry_id and row.entry_version and _entry_version(session, row.entry_id) != row.entry_version:
        outcome = "stale"  # the entry changed after it was asked: nothing approved is applied to other content
    return settle(session, row, outcome, user_id=user_id, note=note, choice=picked, logger=logger)


def _picked(row: WorkflowApprovalModel, choice) -> str | None:
    """The chosen label of an approval with choices (given as the label, or its index); None for one without."""
    offered = row.choices or []
    if not offered:
        return None
    if choice in (None, ""):
        raise ApprovalError("Pick one of the choices to approve.", 422)
    if isinstance(choice, int) and not isinstance(choice, bool) and 0 <= choice < len(offered):
        return offered[choice]
    if isinstance(choice, str) and choice.strip() in offered:
        return choice.strip()
    raise ApprovalError(f"No such choice. The choices are: {', '.join(offered)}.", 422)


def settle(
    session, row: WorkflowApprovalModel, outcome: str, *, user_id=None, note: str | None = None, choice: str | None = None, logger=None
) -> WorkflowApprovalModel:
    """Record the outcome — claimed first, so two deciders can't both resume it — and resume the run."""
    from sqlalchemy import update

    claimed = session.execute(
        update(WorkflowApprovalModel)
        .where(WorkflowApprovalModel.id == row.id, WorkflowApprovalModel.status == APPROVAL_PENDING)
        .values(status=outcome, decided_by=user_id, decided_at=_now(), note=(note or "").strip() or None, choice=choice)
    ).rowcount
    session.commit()
    if not claimed:
        session.refresh(row)
        raise ApprovalError(f"It was already decided: {row.status}.")
    session.refresh(row)
    _stamp_picture(session, row, logger=logger)
    from .engine import resume_after_approval

    resume_after_approval(session, row, logger=logger)
    _emit(session, row, None, EventTypes.workflow_approval_decided, user_id=user_id)
    return row


# Written onto the pictured asset's metadata when an approval that showed it is settled (see _stamp_picture).
DECISIONS_KEPT = ("approved", "denied", "expired", "stale")


def _stamp_picture(session, row: WorkflowApprovalModel, *, logger=None) -> None:
    """An approval that showed a picture leaves its outcome on that asset: ``metadata.approval`` = the decision, who
    and when, the note, and the approval's id. A denied generated image is kept in the library like any other, so
    without this nothing would tell it from one that was kept — the asset page says it, the library filters on it
    (``decision`` in services/item_query.py), and a housekeeping workflow can trash denied pictures later. The URL
    must be one of this workspace's assets (its storage key in it); any other picture is left alone. Best-effort: a
    failure here never undoes the decision."""
    import logging

    from sqlalchemy.orm.attributes import flag_modified

    from marvin.db.models.platform import Assets
    from marvin.db.models.users.users import Users

    if not row.image_url or row.status not in DECISIONS_KEPT:
        return
    try:
        asset = next(
            (
                a
                for a in session.query(Assets).filter(Assets.group_id == row.group_id, Assets.storage_key.isnot(None))
                if a.storage_key in row.image_url
            ),
            None,
        )
        if asset is None:
            return
        decider = session.get(Users, row.decided_by) if row.decided_by else None
        meta = dict(asset.metadata_json or {})
        meta["approval"] = {
            "decision": row.status,
            "decided_by": str(row.decided_by) if row.decided_by else None,
            "decided_by_name": getattr(decider, "full_name", None) or getattr(decider, "username", None),
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "note": row.note,
            "approval_id": str(row.id),
        }
        asset.metadata_json = meta
        flag_modified(asset, "metadata_json")
        session.commit()
    except Exception:  # noqa: BLE001 — the decision stands either way
        session.rollback()
        (logger or logging.getLogger(__name__)).warning("approval %s: could not record the decision on its picture", row.id, exc_info=True)


def expire_due(session, *, logger=None, now: datetime | None = None) -> int:
    """Settle every pending approval past its time as `expired` (the run goes on, so it can act on that)."""
    due = (
        session.query(WorkflowApprovalModel)
        .filter(WorkflowApprovalModel.status == APPROVAL_PENDING, WorkflowApprovalModel.expires_at <= (now or _now()))
        .limit(MAX_PENDING_LIST)
        .all()
    )
    done = 0
    for row in due:
        try:
            settle(session, row, "expired", logger=logger)
            done += 1
        except ApprovalError:
            continue  # decided meanwhile
    return done


def count_pending(session, group_id, role: int) -> int:
    from sqlalchemy import func

    return (
        session.query(func.count(WorkflowApprovalModel.id))
        .filter(WorkflowApprovalModel.group_id == group_id, WorkflowApprovalModel.status == APPROVAL_PENDING, WorkflowApprovalModel.min_role <= role)
        .scalar()
        or 0
    )


def _emit(session, row: WorkflowApprovalModel, automation, event_type, *, user_id=None) -> None:
    """workflow_approval_requested / _decided — best-effort: a failed dispatch never undoes the park or the decision."""
    import logging

    try:
        from marvin.db.models.groups.automations import WorkspaceAutomationModel
        from marvin.services.event_bus_service.event_bus_service import EventBusService
        from marvin.services.event_bus_service.event_types import EventWorkflowApprovalData

        automation = automation or session.get(WorkspaceAutomationModel, row.automation_id)
        data = EventWorkflowApprovalData(
            approval_id=row.id,
            automation_id=row.automation_id,
            automation_name=getattr(automation, "name", None),
            automation_slug=getattr(automation, "slug", None),
            message=row.message,
            min_role=row.min_role,
            status=row.status,
            entry_id=row.entry_id,
            expires_at=row.expires_at.isoformat(),
            note=row.note,
            image_url=row.image_url,
        )
        verb = "is waiting for approval" if event_type == EventTypes.workflow_approval_requested else f"approval: {row.status}"
        EventBusService(bg_tasks=None).dispatch(
            integration_id="automations",
            group_id=row.group_id,
            event_type=event_type,
            document_data=data,
            message=f"{getattr(automation, 'name', 'A workflow')} {verb} — {row.message}",
            user_id=user_id,
            entity_id=row.id,
            entity_type="workflow_approval",
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning(f"workflow approval event {event_type.name} not sent: {e}")
