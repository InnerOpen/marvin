"""Where a run stands, for whoever started it: a page with a Run button, a CLI or an agent waiting on it.

One run is seldom the whole story. A run that reaches an approval or a wait step ends there (``waiting``) and a new
run goes on from the next step once it is decided or its time comes; a run whose last step queued a worker job is over
long before the job is. ``run_state`` follows both, so one question answers "what is it doing now": the run, the runs
that went on from it (``resumed_execution_id`` on the approval or the wait, at most MAX_HOPS deep), the approvals still
waiting on a person, and the job its last step made (services/automation/watch.py).

It says how far the run has got, never what its steps returned: outputs and the log stay on the admin's Runs page.
An integration's scheduled retry of a failed step is not followed: that run failed, and says so.
"""

from typing import Any

from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.workflow_approvals import APPROVAL_PENDING, WorkflowApprovalModel
from marvin.db.models.groups.workflow_waits import WorkflowWaitModel

from . import watch
from .authz import ROLE_ADMIN

MAX_HOPS = 10  # approvals or waits one run is followed past
FAILED = ("failed", "partial")
OVER = ("done", "failed", "cancelled")  # the states that will not change


def run_state(session, group_id, execution_id, *, role: int) -> dict | None:
    """The state of the run `execution_id` of this workspace as it is now (the shape of schemas WorkflowRunState), or
    None when the workspace has no such run. `role` is the reader's workspace rank: an approval above it is named
    without its question."""
    root = session.get(AutomationExecutionModel, execution_id)
    if root is None or root.group_id != group_id:
        return None
    runs, approvals = _followed(session, root)
    automation = session.get(WorkspaceAutomationModel, root.automation_id) if root.automation_id else None
    pending = [a for a in approvals if a.status == APPROVAL_PENDING]
    steps_total = len((root.definition_snapshot or {}).get("actions") or [])
    steps_ok, steps_failed = _steps_so_far(session, runs, steps_total)
    state = _state(runs, pending, automation)
    error = next((r.error for r in runs if r.status in FAILED), None) if state == "failed" else None
    job = _job(session, group_id, runs[-1]) if state == "done" else None
    if job and not job["finished"]:
        state = "working"
    elif job and job["status"] == "failed":
        state, error = "failed", f"The {job['kind']} job it started failed."
    elif root.status == "running" and len(runs) == 1 and not steps_ok + steps_failed:
        state = "starting"
    return {
        "execution_id": root.id,
        "automation_slug": root.automation_slug,
        "automation_name": getattr(automation, "name", None),
        "state": state,
        "started_at": root.started_at,
        "finished_at": max((r.finished_at for r in runs if r.finished_at), default=None) if state in OVER else None,
        "error": error,
        "steps_total": steps_total,
        "steps_ok": steps_ok,
        "steps_failed": steps_failed,
        "waiting_on": [
            {
                "approval_id": a.id,
                "message": a.message if a.min_role <= role else None,
                "approvers": "admin" if a.min_role >= ROLE_ADMIN else "editor",
            }
            for a in pending
        ],
        "continued_by": runs[-1].id if len(runs) > 1 else None,
        "job": job,
    }


def _followed(session, root) -> tuple[list, list]:
    """The run and the runs that went on from it after an approval or a wait, oldest first, and every approval they
    asked. A run over several entries may park one approval each, so this is a tree walked a level at a time."""
    runs, approvals, level = [root], [], [root.id]
    for _ in range(MAX_HOPS):
        parked: list[Any] = []
        for model in (WorkflowApprovalModel, WorkflowWaitModel):
            parked += session.query(model).filter(model.group_id == root.group_id, model.execution_id.in_(level)).all()
        approvals += [p for p in parked if isinstance(p, WorkflowApprovalModel)]
        went_on = [p.resumed_execution_id for p in parked if p.resumed_execution_id]
        if not went_on:
            break
        resumed = (
            session.query(AutomationExecutionModel)
            .filter(AutomationExecutionModel.group_id == root.group_id, AutomationExecutionModel.id.in_(went_on))
            .order_by(AutomationExecutionModel.started_at)
            .all()
        )
        runs += resumed
        level = [r.id for r in resumed]
    return runs, sorted(approvals, key=lambda a: a.created_at)


def _state(runs: list, pending: list, automation) -> str:
    """One word for the run and the runs that went on from it (before its job is looked at)."""
    statuses = {r.status for r in runs}
    if pending:
        return "waiting"
    if "running" in statuses:
        return "running"
    if "waiting" in statuses:
        # Parked with nobody asked: at a wait step, or a decision is being applied (deciding answers before the run
        # goes on). Neither ever goes on once the workflow is off or gone (engine.resume_after_approval / _wait).
        return "running" if automation is not None and automation.enabled else "cancelled"
    if statuses & set(FAILED):
        return "failed"
    return "cancelled" if "cancelled" in statuses else "done"


def _steps_so_far(session, runs: list, steps_total: int) -> tuple[int, int]:
    """(finished, failed) steps recorded so far, read from the step records: a run's own counts are written only when
    it ends. A skipped step is finished; a step waiting on a person is not. The workflow's `on_failure` steps are left
    out: the engine records them after the workflow's own (from index `steps_total` on)."""
    from sqlalchemy import func

    step = AutomationActionExecutionModel
    query = session.query(step.status, func.count(step.id)).filter(step.execution_id.in_([r.id for r in runs]))
    if steps_total:
        query = query.filter(step.action_index < steps_total)
    by_status = dict(query.group_by(step.status).all())
    return by_status.get("success", 0) + by_status.get("skipped", 0), by_status.get("failed", 0)


def _job(session, group_id, run) -> dict | None:
    """The worker job the run's last finished step made or changed (its output's `entry_id`), as it stands now; None
    when that step names no entry or the entry is not a job."""
    from marvin.db.models.platform.entries import Entries

    step = AutomationActionExecutionModel
    last = (
        session.query(step)
        .filter(step.execution_id == run.id, step.status == "success")
        .order_by(step.target_index.desc(), step.action_index.desc())
        .first()
    )
    entry_id = watch.entry_of({"result": last.output_snapshot}) if last is not None else None
    entry = _entry(session, Entries, entry_id)
    if entry is None or entry.group_id != group_id:
        return None
    found = watch.outcome(entry.slug, entry.data_json)
    return {"entry_id": entry.id, **{k: found[k] for k in ("slug", "kind", "status", "finished")}} if found else None


def _entry(session, model, entry_id: str | None):
    import uuid

    try:
        return session.get(model, uuid.UUID(entry_id)) if entry_id else None
    except ValueError:
        return None
