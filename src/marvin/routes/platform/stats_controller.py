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
    inbox: int = 0  # entries in the inbox: form submissions and AI-written entries waiting for triage
    drafts: int = 0  # entries in draft
    needs_review: int = 0  # entries in Needs review: flagged submissions, entries a workflow sent there (a refused signup)
    ai_suggestions: int = 0  # entities with a pending AI write-back (suggestion_json)
    failures: int = 0  # failed executions in the last 7 days (tasks/webhooks/AI)


class DashboardData(_MarvinModel):
    recent_activity: list[RecentEvent] = []
    attention: AttentionCounts = AttentionCounts()


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
            entries=_count(session, Entries, workspace_id, Entries.status != "trashed"),  # the Trash is out of sight
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

        inbox = _c(select(func.count(Entries.id)).where(Entries.group_id == gid, Entries.status == "inbox"))
        drafts = _c(select(func.count(Entries.id)).where(Entries.group_id == gid, Entries.status == "draft"))
        needs_review = _c(select(func.count(Entries.id)).where(Entries.group_id == gid, Entries.status == "needs_review"))

        suggestions = _c(select(func.count(Entries.id)).where(Entries.group_id == gid, Entries.suggestion_json.isnot(None)))
        suggestions += sum(
            _c(select(func.count(m.id)).where(m.group_id == gid, m.suggestion_json.isnot(None), m.trashed_at.is_(None))) for m in (Assets, Resources)
        )
        # …but not a suggestion waiting on an entry in the Trash.
        trashed_suggestions = select(func.count(Entries.id)).where(
            Entries.group_id == gid, Entries.suggestion_json.isnot(None), Entries.status == "trashed"
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

        return DashboardData(
            recent_activity=recent,
            attention=AttentionCounts(inbox=inbox, drafts=drafts, needs_review=needs_review, ai_suggestions=suggestions, failures=failures),
        )
