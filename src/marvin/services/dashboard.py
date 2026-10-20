"""The workspace dashboard beyond counts: what waits on the member (approvals, parked runs, how old the oldest
draft is), what happens in the next week (scheduled publishes, waits that resume, scheduled tasks), a health
strip (backups, integrations, deliveries, failed runs, email and push) and workflow runs by day for a sparkline.

Every query is guarded: one failing panel shows empty rather than sinking the page, the rule the dashboard
has always had. Times come back timezone-aware UTC whatever the column stores.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import func, or_, select

from marvin.db.models.groups.automation_executions import AutomationExecutionModel
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
from marvin.db.models.groups.workflow_waits import WorkflowWaitModel
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.schemas._marvin import _MarvinModel
from marvin.services.entry_listing import is_listed_type, listed_clause

UPCOMING_DAYS = 7
UPCOMING_LIMIT = 8
APPROVALS_SHOWN = 3  # decided inline on the dashboard; the rest on the Approvals page
SPARKLINE_DAYS = 14
NOT_PUBLISHABLE = ("published", "archived", "trashed")  # a scheduled publish_at on these never fires
RUN_OK = ("success", "resumed")
RUN_FAILED = ("failed", "partial")
PUBLISHING_WEEKS = 12
RECENT_FOR_YOU = 5
PIPELINE_STATUSES = ("inbox", "draft", "needs_review", "approved", "published")


class ApprovalBrief(_MarvinModel):
    id: str
    automation_id: str | None = None
    automation_name: str | None = None
    message: str
    choices: list[str] | None = None
    entry_title: str | None = None
    created_at: datetime | None = None
    image_url: str | None = None  # the picture the question is about, when the step named one


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


class TypeBrief(_MarvinModel):
    slug: str
    name: str
    icon: str | None = None
    color: str | None = None


class WeekPublished(_MarvinModel):
    week: date  # the Monday
    by_type: dict[str, int] = {}  # entry type slug → entries published that week


class PublishingPulse(_MarvinModel):
    """Entries published per week, by type: what the workspace shipped."""

    weeks: list[WeekPublished] = []  # oldest first, a row for every week
    types: list[TypeBrief] = []  # the types that appear, for the legend
    total: int = 0


class EntryBrief(_MarvinModel):
    id: str
    title: str
    status: str
    type_slug: str | None = None
    touched_at: datetime | None = None


class TypeStatusRow(TypeBrief):
    """One entry type's pipeline: how many entries sit in each status."""

    inbox: int = 0
    draft: int = 0
    needs_review: int = 0
    approved: int = 0
    published: int = 0


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
                image_url=a.image_url,
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
    oldest = _scalar(
        session,
        select(func.min(Entries.created_at)).where(Entries.group_id == group_id, Entries.status == status, listed_clause(session, group_id)),
        None,
    )
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
            .where(Entries.status.notin_(NOT_PUBLISHABLE), listed_clause(session, group_id))
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


def _types(session, group_id, ids=None) -> dict:
    """The workspace's entry types by id — plus the system types (group_id NULL, available everywhere) among `ids`."""
    own = EntryTypes.group_id == group_id
    stmt = select(EntryTypes).where(own if ids is None else or_(own, EntryTypes.group_id.is_(None)))
    if ids is not None:
        stmt = stmt.where(EntryTypes.id.in_(list(ids)))
    try:
        return {t.id: t for t in session.execute(stmt).scalars().all()}
    except Exception:
        session.rollback()
        return {}


def _brief(t) -> TypeBrief:
    return TypeBrief(slug=t.slug, name=t.name, icon=t.icon, color=t.color)


def published_by_week(session, group_id, now: datetime) -> PublishingPulse:
    """What was published in each of the last PUBLISHING_WEEKS weeks, by entry type — a row for every week."""
    monday = (now.date() - timedelta(days=now.weekday())) - timedelta(weeks=PUBLISHING_WEEKS - 1)
    weeks = {monday + timedelta(weeks=i): WeekPublished(week=monday + timedelta(weeks=i)) for i in range(PUBLISHING_WEEKS)}
    # Counted per day and bucketed into weeks here: date_trunc("week", ...) exists only on Postgres.
    day_col = func.date(Entries.published_at, type_=sa.Date)
    try:
        rows = session.execute(
            select(day_col, Entries.entry_type_id, func.count(Entries.id))
            .where(Entries.group_id == group_id, Entries.status == "published", Entries.published_at.isnot(None))
            .where(Entries.published_at >= datetime.combine(monday, datetime.min.time()), listed_clause(session, group_id))
            .group_by(day_col, Entries.entry_type_id)
        ).all()
    except Exception:
        session.rollback()
        return PublishingPulse(weeks=list(weeks.values()))
    types = _types(session, group_id, {type_id for _, type_id, _ in rows})
    total = 0
    for day, type_id, count in rows:
        week = day - timedelta(days=day.weekday())
        row, t = weeks.get(week), types.get(type_id)
        if row is None or t is None:
            continue
        row.by_type[t.slug] = row.by_type.get(t.slug, 0) + int(count)
        total += int(count)
    used = {slug for w in weeks.values() for slug in w.by_type}
    legend = sorted((_brief(t) for t in types.values() if t.slug in used), key=lambda b: b.name.lower())
    return PublishingPulse(weeks=list(weeks.values()), types=legend, total=total)


def recent_for_you(session, group_id, user_id, now: datetime) -> list[EntryBrief]:
    """The entries this member touched most recently (their own events on entries), newest first — "pick up where
    you left off". Trashed entries are left out."""
    if not user_id:
        return []
    try:
        rows = session.execute(
            select(EventLogModel.entity_id, func.max(EventLogModel.occurred_at).label("last"))
            .where(EventLogModel.workspace_id == group_id, EventLogModel.user_id == user_id, EventLogModel.entity_type == "entry")
            .where(EventLogModel.entity_id.isnot(None))
            .group_by(EventLogModel.entity_id)
            .order_by(func.max(EventLogModel.occurred_at).desc())
            .limit(RECENT_FOR_YOU * 2)  # some may be trashed or gone
        ).all()
        if not rows:
            return []
        entries = {e.id: e for e in session.execute(select(Entries).where(Entries.id.in_([r.entity_id for r in rows]))).scalars().all()}
    except Exception:
        session.rollback()
        return []
    types = _types(session, group_id, {e.entry_type_id for e in entries.values()})
    out = []
    for entity_id, last in rows:
        e = entries.get(entity_id)
        if e is None or e.status == "trashed":
            continue
        t = types.get(e.entry_type_id)
        if t is not None and not is_listed_type(t):  # an internal type's entries aren't "yours to pick up"
            continue
        out.append(EntryBrief(id=str(e.id), title=e.title or "Untitled", status=e.status, type_slug=t.slug if t else None, touched_at=_utc(last)))
        if len(out) == RECENT_FOR_YOU:
            break
    return out


def by_type_status(session, group_id) -> list[TypeStatusRow]:
    """Every entry type's pipeline (inbox → draft → needs review → approved → published), by name."""
    try:
        counts = session.execute(
            select(Entries.entry_type_id, Entries.status, func.count(Entries.id))
            .where(Entries.group_id == group_id, Entries.status.in_(PIPELINE_STATUSES), listed_clause(session, group_id))
            .group_by(Entries.entry_type_id, Entries.status)
        ).all()
    except Exception:
        session.rollback()
        counts = []
    # Every type of the workspace's own, and any system type its entries use.
    types = {**_types(session, group_id), **_types(session, group_id, {type_id for type_id, _, _ in counts})}
    types = {k: t for k, t in types.items() if is_listed_type(t)}  # an internal type has no pipeline to show
    if not types:
        return []
    rows = {t.id: TypeStatusRow(**_brief(t).model_dump()) for t in types.values()}
    for type_id, status, count in counts:
        if (row := rows.get(type_id)) is not None:
            setattr(row, status, int(count))
    return sorted(rows.values(), key=lambda r: r.name.lower())
