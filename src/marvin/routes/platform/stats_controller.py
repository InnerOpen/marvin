"""Platform stats endpoint — returns workspace-scoped resource counts."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import UUID4
from sqlalchemy import func, select

from marvin.db.models.groups import GroupWebhooksModel
from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.db.models.groups.secrets import WorkspaceSecret
from marvin.db.models.groups.variables import WorkspaceVariable
from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
from marvin.db.models.platform import Assets, Collections, Entries, Resources
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskExecutionLogModel, ScheduledTaskModel
from marvin.routes._base import BaseUserController, controller
from marvin.schemas._marvin import _MarvinModel
from marvin.services import dashboard as dash
from marvin.services.dashboard import ApprovalBrief, EntryBrief, HealthStrip, PublishingPulse, RunsDay, TypeStatusRow, UpcomingItem
from marvin.services.entry_listing import listed_clause

router = APIRouter(prefix="/stats")


class WorkspaceStats(_MarvinModel):
    entries: int = 0
    assets: int = 0
    collections: int = 0
    webhooks: int = 0
    scheduled_tasks: int = 0
    secrets: int = 0
    variables: int = 0
    members: int = 0
    ai_executions: int = 0
    ai_embeddings: int = 0
    ai_tokens: int = 0
    ai_cost_usd: float = 0.0


class RecentEvent(_MarvinModel):
    event_type: str
    message: str
    entity_type: str | None = None
    entity_id: str | None = None
    occurred_at: datetime | None = None


class AttentionCounts(_MarvinModel):
    # Counted apart because the panel links each to its own entries filter; a combined number linked to
    # ?status=draft showed 11 "drafts" over a list of 2.
    inbox: int = 0  # entries in the inbox: submissions of forms that go to Entries, and AI-written entries waiting for triage
    drafts: int = 0  # entries in draft
    needs_review: int = 0  # entries in Needs review: flagged submissions, entries a workflow sent there (a refused signup)
    ai_suggestions: int = 0  # entities with a pending AI write-back (suggestion_json)
    failures: int = 0  # failed executions in the last 7 days (tasks/webhooks/AI)
    approvals: int = 0  # workflow approvals this member may decide
    parked_runs: int = 0  # workflow runs stopped at a wait or an approval
    oldest_draft_days: int | None = None  # age of the oldest draft / inbox entry — "4 drafts" reads differently from "a draft for 23 days"
    oldest_inbox_days: int | None = None
    audience_new: int = 0  # new + suspicious submissions of the forms that go to the Audience (internal: not in the counts above); 0 below EDITOR
    # Signups that need a look (Audience › Subscribers: the mailing list refused it, or the spam protection held it); 0 below EDITOR. A pending
    # signup (the reader hasn't confirmed) is routine and nobody's to-do, so only problems are here (the sidebar badge counts both).
    audience_problems: int = 0
    # Hand-offs to another system (Settings › Automation › Results): failures nobody dismissed, and ones still in flight after 24 hours with no
    # reply. One in flight is routine, so it isn't here. 0 below EDITOR.
    results_failed: int = 0
    results_no_reply: int = 0
    # Workflows (and, as their pages land, webhooks and scheduled tasks) that need a look — one number from services/automation/attention.py,
    # with the page to open first. 0 below ADMIN, who are the ones who manage automations.
    automation: int = 0
    automation_page: str | None = None


class DashboardData(_MarvinModel):
    recent_activity: list[RecentEvent] = []
    attention: AttentionCounts = AttentionCounts()
    approvals: list[ApprovalBrief] = []  # the oldest few, decided inline
    upcoming: list[UpcomingItem] = []  # the next 7 days: publishes, resumes, scheduled tasks
    health: HealthStrip = HealthStrip()
    runs_by_day: list[RunsDay] = []  # 14 days for the sparkline, oldest first
    publishing: PublishingPulse = PublishingPulse()  # 12 weeks of published entries, by type
    recent_for_you: list[EntryBrief] = []  # the caller's last-touched entries
    by_type: list[TypeStatusRow] = []  # each entry type's pipeline


def _event_message(e) -> str:
    """A human line for an event — the stored message title if present, else a humanized type."""
    data = e.event_data or {}
    msg = data.get("message") if isinstance(data, dict) else None
    if isinstance(msg, dict) and (msg.get("title") or msg.get("body")):
        return str(msg.get("title") or msg.get("body"))
    if isinstance(msg, str) and msg:
        return msg
    return (e.event_type or "event").replace("_", " ").replace(".", " ").strip().capitalize()


def _count(session, model, group_id: UUID4, *where) -> int:
    """Return a group-scoped row count, defaulting to 0 on any error."""
    try:
        return session.execute(select(func.count(model.id)).where(model.group_id == group_id, *where)).scalar() or 0
    except Exception:
        return 0


def _sum(session, model, column, group_id: UUID4, since: datetime | None = None):
    """Return a group-scoped SUM of `column`, optionally since `since`, defaulting to 0 on error."""
    try:
        stmt = select(func.coalesce(func.sum(column), 0)).where(model.group_id == group_id)
        if since is not None:
            stmt = stmt.where(model.created_at >= since)
        return session.execute(stmt).scalar() or 0
    except Exception:
        return 0


@controller(router)
class StatsController(BaseUserController):
    """Returns resource counts for the current workspace."""

    @router.get("", response_model=WorkspaceStats, summary="Get Workspace Statistics")
    def get_stats(self) -> WorkspaceStats:
        workspace_id: UUID4 = self.group_id
        session = self.repos.session
        month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        try:
            members = self.repos.workspace_members.get_members_by_workspace(workspace_id)
            members_count = len(members)
        except Exception:
            members_count = 0

        return WorkspaceStats(
            # the Trash is out of sight, and so are the entries of an internal type (services/entry_listing.py)
            entries=_count(session, Entries, workspace_id, Entries.status != "trashed", listed_clause(session, workspace_id)),
            assets=_count(session, Assets, workspace_id, Assets.trashed_at.is_(None), Assets.scope == "library"),  # not Ask files
            collections=_count(session, Collections, workspace_id),
            webhooks=_count(session, GroupWebhooksModel, workspace_id),
            scheduled_tasks=_count(session, ScheduledTaskModel, workspace_id),
            secrets=_count(session, WorkspaceSecret, workspace_id),
            variables=_count(session, WorkspaceVariable, workspace_id),
            members=members_count,
            ai_executions=_count(session, AIExecutionModel, workspace_id),
            ai_embeddings=_count(session, AIEmbeddingModel, workspace_id),
            # Tokens + cost are month-to-date usage flows, aligned with the monthly budget limit.
            ai_tokens=int(_sum(session, AIExecutionModel, AIExecutionModel.total_tokens, workspace_id, since=month_start)),
            ai_cost_usd=float(_sum(session, AIExecutionModel, AIExecutionModel.estimated_cost_usd, workspace_id, since=month_start)),
        )

    def _audience(self, gid) -> tuple[int, int]:
        """``(new submissions, problem signups)`` waiting in Audience, for a member who may read it (EDITOR and above)."""
        from fastapi import HTTPException

        from marvin.db.models.users.roles import WorkspaceRole
        from marvin.routes._base.checks import require_workspace_role
        from marvin.services import audience

        session = self.repos.session
        try:
            require_workspace_role(self.user, gid, WorkspaceRole.EDITOR)
            overview = audience.summary(session, gid)
            return int(overview["submissions"]["new"]), int(overview["signups"]["problem"])
        except HTTPException:
            return 0, 0
        except Exception:  # a caller the role helpers can't read, or a failed count: the panel just leaves the line out
            session.rollback()
            return 0, 0

    def _results(self, gid) -> tuple[int, int]:
        """``(failed hand-offs, hand-offs with no reply)`` waiting in Automation results, for a member who may read it (EDITOR and above)."""
        from fastapi import HTTPException

        from marvin.db.models.users.roles import WorkspaceRole
        from marvin.routes._base.checks import require_workspace_role
        from marvin.services import automation_results

        session = self.repos.session
        try:
            require_workspace_role(self.user, gid, WorkspaceRole.EDITOR)
            return automation_results.attention(session, gid)
        except HTTPException:
            return 0, 0
        except Exception:  # a failed count: the panel just leaves the lines out
            session.rollback()
            return 0, 0

    def _automation(self, gid) -> tuple[int, str | None]:
        """``(items needing a look, the page to open first)`` in Automation, for a member who manages it (ADMIN and above)."""
        from fastapi import HTTPException

        from marvin.db.models.users.roles import WorkspaceRole
        from marvin.routes._base.checks import require_workspace_role
        from marvin.services.automation import attention

        session = self.repos.session
        try:
            require_workspace_role(self.user, gid, WorkspaceRole.ADMIN)
            found = attention.summary(session, gid)
            return found["total"], found["first_page"]
        except HTTPException:
            return 0, None
        except Exception:  # a failed count: the panel just leaves the line out
            session.rollback()
            return 0, None

    @router.get("/dashboard", response_model=DashboardData, summary="Dashboard activity + attention queue")
    def get_dashboard(self) -> DashboardData:
        """Recent workspace activity and the "needs attention" counts — draft entries awaiting
        review, pending AI suggestions, and recent execution failures. Every query is guarded so a
        single failure degrades to 0 rather than sinking the whole dashboard."""
        gid: UUID4 = self.group_id
        session = self.repos.session

        recent: list[RecentEvent] = []
        try:
            from marvin.repos.platform.event_log import workspace_events_clause
            from marvin.services.ai.executions import user_sees_every_run, visible_events_clause

            stmt = select(EventLogModel).where(EventLogModel.workspace_id == gid, workspace_events_clause())
            # Other members' AI-run events are admin-only, like the event log.
            visible = visible_events_clause(sees_all=user_sees_every_run(self.user, gid), user_id=self.user.id)
            if visible is not None:
                stmt = stmt.where(visible)
            rows = session.execute(stmt.order_by(EventLogModel.occurred_at.desc()).limit(8)).scalars().all()
            recent = [
                RecentEvent(
                    event_type=e.event_type,
                    message=_event_message(e),
                    entity_type=e.entity_type,
                    entity_id=str(e.entity_id) if e.entity_id else None,
                    occurred_at=e.occurred_at,
                )
                for e in rows
            ]
        except Exception:
            recent = []

        def _c(stmt) -> int:
            try:
                return session.execute(stmt).scalar() or 0
            except Exception:
                return 0

        listed = listed_clause(session, gid)
        inbox = _c(select(func.count(Entries.id)).where(Entries.group_id == gid, Entries.status == "inbox", listed))
        drafts = _c(select(func.count(Entries.id)).where(Entries.group_id == gid, Entries.status == "draft", listed))
        needs_review = _c(select(func.count(Entries.id)).where(Entries.group_id == gid, Entries.status == "needs_review", listed))

        suggestions = _c(select(func.count(Entries.id)).where(Entries.group_id == gid, Entries.suggestion_json.isnot(None), listed))
        suggestions += sum(
            _c(select(func.count(m.id)).where(m.group_id == gid, m.suggestion_json.isnot(None), m.trashed_at.is_(None))) for m in (Assets, Resources)
        )
        # …but not a suggestion waiting on an entry in the Trash.
        trashed_suggestions = select(func.count(Entries.id)).where(
            Entries.group_id == gid, Entries.suggestion_json.isnot(None), Entries.status == "trashed", listed
        )
        suggestions -= _c(trashed_suggestions)

        since = datetime.now(UTC) - timedelta(days=7)
        failures = sum(
            _c(select(func.count(model.id)).where(model.group_id == gid, model.status == "failed", ts >= since))
            for model, ts in (
                (ScheduledTaskExecutionLogModel, ScheduledTaskExecutionLogModel.executed_at),
                (WebhookExecutionLogModel, WebhookExecutionLogModel.executed_at),
                (AIExecutionModel, AIExecutionModel.created_at),
            )
        )

        from marvin.routes._base.checks import _bypasses_workspace_roles
        from marvin.routes.automations.automations_controller import _rank

        now = datetime.now(UTC)
        try:  # a caller the role helpers can't read gets the member-level dashboard, like any other guarded panel
            role, sees_backups = _rank(self.user, gid), _bypasses_workspace_roles(self.user)
        except Exception:
            role, sees_backups = 0, False
        approvals_count, approvals = dash.approvals_waiting(session, gid, role)
        audience_new, audience_problems = self._audience(gid)
        results_failed, results_no_reply = self._results(gid)
        automation, automation_page = self._automation(gid)
        return DashboardData(
            recent_activity=recent,
            attention=AttentionCounts(
                inbox=inbox,
                drafts=drafts,
                needs_review=needs_review,
                ai_suggestions=suggestions,
                failures=failures,
                approvals=approvals_count,
                parked_runs=dash.parked_runs(session, gid),
                oldest_draft_days=dash.oldest_entry_days(session, gid, "draft", now),
                oldest_inbox_days=dash.oldest_entry_days(session, gid, "inbox", now),
                audience_new=audience_new,
                audience_problems=audience_problems,
                results_failed=results_failed,
                results_no_reply=results_no_reply,
                automation=automation,
                automation_page=automation_page,
            ),
            approvals=approvals,
            upcoming=dash.upcoming(session, gid, now),
            health=dash.health(session, gid, now, sees_backups=sees_backups),
            runs_by_day=dash.runs_by_day(session, gid, now),
            publishing=dash.published_by_week(session, gid, now),
            recent_for_you=dash.recent_for_you(session, gid, getattr(self.user, "id", None), now),
            by_type=dash.by_type_status(session, gid),
        )
