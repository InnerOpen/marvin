"""Creating and changing a workflow — the one write path the REST routes and the agent tools share.

`POST /api/automations` and an agent's `draft_workflow` must make the same row: the same slug from the
name, the same conflict, the same structural gate (`validation.structural_issues`), `created_by` set to
the person (the workflow then runs with that person's role — see authz.py), and the same backing
scheduled task for a schedule trigger. So the route and the tool both call these, and only translate
the errors into their own shape (an HTTP status, or an `{error, issues}` the model can act on).
"""

import re
from typing import Any

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.schemas.group.automation import AutomationCreate, AutomationUpdate


class WorkflowError(Exception):
    """A write the workspace refuses. ``status`` is the HTTP status the REST route answers with;
    ``detail`` is what it answers (a string, or the ``{message, issues}`` of a malformed definition)."""

    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(detail if isinstance(detail, str) else detail.get("message", "invalid workflow"))
        self.status = status
        self.detail = detail


class SlugConflict(WorkflowError):
    def __init__(self, slug: str) -> None:
        super().__init__(409, f"Automation slug '{slug}' already exists.")
        self.slug = slug


class InvalidDefinition(WorkflowError):
    def __init__(self, issues: list[dict]) -> None:
        super().__init__(422, {"message": "The workflow definition is not well-formed.", "issues": issues})
        self.issues = issues


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "automation"


def require_valid_definition(definition: dict | None) -> None:
    """Gate the write path on the definition's *structure* (the Pydantic source of truth). Rejects a
    malformed definition — unknown action kind / trigger type, missing required field, wrong type —
    with the structured issues. Semantic 'won't match anything' warnings are advisory (POST /validate)
    and do NOT block here."""
    from .validation import structural_issues

    issues = structural_issues(definition)
    if issues:
        raise InvalidDefinition(issues)


def create_workflow(session, group_id, user_id, data: AutomationCreate) -> WorkspaceAutomationModel:
    """Create a workflow as `user_id` — its author, whose role its steps run with."""
    slug = data.slug or slugify(data.name)
    if session.query(WorkspaceAutomationModel).filter_by(group_id=group_id, slug=slug).first():
        raise SlugConflict(slug)
    require_valid_definition(data.definition)

    payload = data.model_dump()
    payload["slug"] = slug
    row = WorkspaceAutomationModel(session=session, group_id=group_id, created_by=user_id, **payload)
    session.add(row)
    session.commit()
    session.refresh(row)
    sync_schedule(session, group_id, row)
    return row


def update_workflow(session, group_id, row: WorkspaceAutomationModel, data: AutomationUpdate) -> WorkspaceAutomationModel:
    if data.definition is not None:
        require_valid_definition(data.definition)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    session.commit()
    session.refresh(row)
    sync_schedule(session, group_id, row)
    return row


def delete_workflow(session, group_id, row: WorkspaceAutomationModel) -> None:
    delete_schedule(session, group_id, row.id)
    session.delete(row)
    session.commit()


# ── Schedule-trigger backing task (trigger.type="schedule") ────────────────
def _schedule_slug(automation_id) -> str:
    return f"wf-{automation_id}"


def _find_schedule_task(session, group_id, automation_id):
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    return session.query(ScheduledTaskModel).filter_by(group_id=group_id, slug=_schedule_slug(automation_id)).first()


def sync_schedule(session, group_id, automation) -> None:
    """Keep the backing `run_automation` scheduled task in sync with the automation's trigger.

    trigger.type="schedule" → upsert a task (`schedule_type`/`schedule_config` from the trigger,
    e.g. interval_seconds); any other trigger type → remove the backing task if one exists.
    """
    from marvin.repos.repository_factory import AllRepositories

    trig = automation.trigger or {}
    existing = _find_schedule_task(session, group_id, automation.id)

    if trig.get("type") != "schedule":
        if existing:
            session.delete(existing)
            session.commit()
        return

    payload = {
        "name": f"Workflow: {automation.name}",
        "description": f"Runs the '{automation.name}' workflow on a schedule.",
        "enabled": bool(automation.enabled),
        "schedule_type": trig.get("schedule_type", "interval"),
        "schedule_config": trig.get("schedule_config") or {},
        "task_type": "run_automation",
        "task_config": {"automation_id": str(automation.id)},
    }
    tasks = AllRepositories(session, group_id=group_id).scheduled_tasks
    if existing:
        tasks.update(existing.id, payload)
    else:
        tasks.create({**payload, "slug": _schedule_slug(automation.id)})


def delete_schedule(session, group_id, automation_id) -> None:
    existing = _find_schedule_task(session, group_id, automation_id)
    if existing:
        session.delete(existing)
        session.commit()
