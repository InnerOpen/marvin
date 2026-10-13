"""The workspace dashboard beyond counts: what waits on the member (approvals, parked runs, how old the oldest
draft is), what happens in the next week (scheduled publishes, waits that resume, scheduled tasks), a health
strip (backups, integrations, deliveries, failed runs, email and push) and workflow runs by day for a sparkline.

Every query is guarded: one failing panel shows empty rather than sinking the page, the rule the dashboard
has always had. Times come back timezone-aware UTC whatever the column stores.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from marvin.db.models.groups.automation_executions import AutomationExecutionModel
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
from marvin.db.models.groups.workflow_waits import WorkflowWaitModel
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.schemas._marvin import _MarvinModel

UPCOMING_DAYS = 7
UPCOMING_LIMIT = 8
APPROVALS_SHOWN = 3  # decided inline on the dashboard; the rest on the Approvals page
SPARKLINE_DAYS = 14
NOT_PUBLISHABLE = ("published", "archived", "trashed")  # a scheduled publish_at on these never fires
RUN_OK = ("success", "resumed")
RUN_FAILED = ("failed", "partial")


class ApprovalBrief(_MarvinModel):
    id: str
    automation_id: str | None = None
    automation_name: str | None = None
    message: str
    choices: list[str] | None = None
    entry_title: str | None = None
    created_at: datetime | None = None


class UpcomingItem(_MarvinModel):
    kind: str  # publish | resume | task
    at: datetime
    title: str
    entity_id: str | None = None  # the entry, for a publish
    automation_id: str | None = None  # the workflow and its parked run, for a resume
    execution_id: str | None = None


class HealthStrip(_MarvinModel):
    backup_state: str | None = None  # ok | partial | failed | overdue; None when the caller can't see backups
    backup_last_success: datetime | None = None
    integrations_total: int = 0
    integrations_failing: int = 0
    webhook_failures_24h: int = 0
    workflow_failures_7d: int = 0
    email_ready: bool = False
    push_ready: bool = False


class RunsDay(_MarvinModel):
    day: date
    ok: int = 0
    failed: int = 0


def _utc(value: datetime | None) -> datetime | None:
    """Naive columns hold UTC; hand every time out aware so the page needn't guess."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _scalar(session, stmt, default=0):
    try:
        value = session.execute(stmt).scalar()
        return default if value is None else value
    except Exception:
        session.rollback()
        return default


def _days_since(value: datetime | None, now: datetime) -> int | None:
    value = _utc(value)
    return None if value is None else max(0, (now - value).days)


def approvals_waiting(session, group_id, role: int) -> tuple[int, list[ApprovalBrief]]:
    """How many approvals a member at `role` may decide, and the oldest few to decide right on the dashboard."""
    from marvin.services.automation.approvals import pending

    try:
        rows = pending(session, group_id, role)
    except Exception:
        session.rollback()
        return 0, []
    briefs = []
    for a in rows[:APPROVALS_SHOWN]:
        automation = session.get(WorkspaceAutomationModel, a.automation_id) if a.automation_id else None
        entry = session.get(Entries, a.entry_id) if a.entry_id else None
        briefs.append(
            ApprovalBrief(
                id=str(a.id),
                automation_id=str(a.automation_id) if a.automation_id else None,
                automation_name=automation.name if automation else None,
                message=a.message or "",
                choices=[str(c) for c in a.choices] if a.choices else None,
                entry_title=entry.title if entry else None,
                created_at=_utc(a.created_at),
            )
        )
    return len(rows), briefs


def parked_runs(session, group_id) -> int:
    """Runs stopped at a wait or an approval step."""
    return _scalar(
        session,
        select(func.count(AutomationExecutionModel.id)).where(
            AutomationExecutionModel.group_id == group_id, AutomationExecutionModel.status == "waiting"
        ),
    )


def oldest_entry_days(session, group_id, status: str, now: datetime) -> int | None:
    """How many days the oldest entry in `status` has been around (by creation), or None when there are none."""
    oldest = _scalar(session, select(func.min(Entries.created_at)).where(Entries.group_id == group_id, Entries.status == status), None)
    return _days_since(oldest, now)


def upcoming(session, group_id, now: datetime) -> list[UpcomingItem]:
    """What the next UPCOMING_DAYS hold, soonest first: scheduled publishes, waits that resume, scheduled tasks."""
    until = now + timedelta(days=UPCOMING_DAYS)
    naive_now, naive_until = now.replace(tzinfo=None), until.replace(tzinfo=None)
    items: list[UpcomingItem] = []
    try:
        entries = session.execute(
            select(Entries.id, Entries.title, Entries.publish_at)
            .where(Entries.group_id == group_id, Entries.publish_at > naive_now, Entries.publish_at <= naive_until)
            .where(Entries.status.notin_(NOT_PUBLISHABLE))
            .order_by(Entries.publish_at)
            .limit(UPCOMING_LIMIT)
        ).all()
        items += [UpcomingItem(kind="publish", at=_utc(at), title=title or "Untitled", entity_id=str(eid)) for eid, title, at in entries]
    except Exception:
        session.rollback()
    try:
        waits = session.execute(
            select(
                WorkflowWaitModel.resume_at,
                WorkflowWaitModel.automation_id,
                WorkflowWaitModel.execution_id,
                WorkflowWaitModel.note,
                WorkspaceAutomationModel.name,
            )
            .join(WorkspaceAutomationModel, WorkspaceAutomationModel.id == WorkflowWaitModel.automation_id, isouter=True)
            .where(WorkflowWaitModel.group_id == group_id, WorkflowWaitModel.status == "waiting")
            .where(WorkflowWaitModel.resume_at > naive_now, WorkflowWaitModel.resume_at <= naive_until)
            .order_by(WorkflowWaitModel.resume_at)
            .limit(UPCOMING_LIMIT)
        ).all()
        for at, automation_id, execution_id, note, name in waits:
            title = f"{name or 'Workflow'} resumes" + (f" — {note}" if note else "")
            items.append(
                UpcomingItem(
                    kind="resume", at=_utc(at), title=title,
                    automation_id=str(automation_id) if automation_id else None,
                    execution_id=str(execution_id) if execution_id else None,
                )
            )  # fmt: skip
    except Exception:
        session.rollback()
    try:
        tasks = session.execute(
            select(ScheduledTaskModel.name, ScheduledTaskModel.next_run_at)
            .where(ScheduledTaskModel.group_id == group_id, ScheduledTaskModel.enabled.is_(True))
            .where(ScheduledTaskModel.next_run_at > now, ScheduledTaskModel.next_run_at <= until)
            .order_by(ScheduledTaskModel.next_run_at)
            .limit(UPCOMING_LIMIT)
        ).all()
        items += [UpcomingItem(kind="task", at=_utc(at), title=name) for name, at in tasks]
    except Exception:
        session.rollback()
    return sorted(items, key=lambda i: i.at)[:UPCOMING_LIMIT]


def health(session, group_id, now: datetime, *, sees_backups: bool) -> HealthStrip:
    """The strip of dots: each number is a link to the page that explains it."""
    strip = HealthStrip(
        integrations_total=_scalar(
            session, select(func.count(IntegrationModel.id)).where(IntegrationModel.group_id == group_id, IntegrationModel.enabled.is_(True))
        ),
        integrations_failing=_scalar(
            session,
            select(func.count(IntegrationModel.id)).where(
                IntegrationModel.group_id == group_id, IntegrationModel.enabled.is_(True), IntegrationModel.status == "error"
            ),
        ),
        webhook_failures_24h=_scalar(
            session,
            select(func.count(WebhookExecutionLogModel.id)).where(
                WebhookExecutionLogModel.group_id == group_id,
                WebhookExecutionLogModel.status == "failed",
                WebhookExecutionLogModel.executed_at >= now - timedelta(hours=24),
            ),
        ),
        workflow_failures_7d=_scalar(
            session,
            select(func.count(AutomationExecutionModel.id)).where(
                AutomationExecutionModel.group_id == group_id,
                AutomationExecutionModel.status.in_(RUN_FAILED),
                AutomationExecutionModel.started_at >= now - timedelta(days=7),
            ),
        ),
    )
    try:
        from marvin.services.email.email_senders import email_ready

        strip.email_ready = bool(email_ready(group_id, session))
    except Exception:
        session.rollback()
    try:
        from marvin.services import web_push

        strip.push_ready = bool(web_push.configured())
    except Exception:
        pass
    if sees_backups:  # backup runs are platform-wide, so only a platform admin gets the dot
        try:
            from marvin.services.backup_health import all_targets

            targets = all_targets(session, now)
            worst = ("unknown", "ok", "partial", "overdue", "failed")
            states = [t.state for t in targets]
            strip.backup_state = max(states, key=worst.index) if states else None
            successes = [t.last_success for t in targets if t.last_success]
            strip.backup_last_success = _utc(max(successes)) if successes else None
        except Exception:
            session.rollback()
    return strip


def runs_by_day(session, group_id, now: datetime) -> list[RunsDay]:
    """Workflow runs started on each of the last SPARKLINE_DAYS days, oldest first, a row for every day."""
    first = (now - timedelta(days=SPARKLINE_DAYS - 1)).date()
    days = {first + timedelta(days=i): RunsDay(day=first + timedelta(days=i)) for i in range(SPARKLINE_DAYS)}
    try:
        day_col = func.date(AutomationExecutionModel.started_at)
        rows = session.execute(
            select(day_col, AutomationExecutionModel.status, func.count(AutomationExecutionModel.id))
            .where(AutomationExecutionModel.group_id == group_id)
            .where(AutomationExecutionModel.started_at >= datetime.combine(first, datetime.min.time(), UTC))
            .group_by(day_col, AutomationExecutionModel.status)
        ).all()
    except Exception:
        session.rollback()
        return list(days.values())
    for day, status, count in rows:
        day = date.fromisoformat(str(day)) if not isinstance(day, date) else day
        if (row := days.get(day)) is None:
            continue
        if status in RUN_OK:
            row.ok += count
        elif status in RUN_FAILED:
            row.failed += count
    return list(days.values())
