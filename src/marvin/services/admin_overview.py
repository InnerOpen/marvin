"""Admin → Overview, the platform's own dashboard: a health strip (one dot per thing that can be wrong, each with the
page that explains it), every workspace at a glance, and AI spend by day across the platform with the share the
providers' prompt caches served. Each part is best-effort: one failing never blanks the others.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

logger = logging.getLogger(__name__)

SPEND_DAYS = 30
PRICE_FEED_STALE_HOURS = 48
OK, WARN, BAD, OFF = "ok", "warn", "bad", "off"


@dataclass
class HealthDot:
    key: str
    label: str
    tone: str  # ok | warn | bad | off
    href: str


@dataclass
class WorkspaceRow:
    id: str
    name: str
    slug: str
    entries: int = 0
    members: int = 0
    ai_spend_month: float = 0.0
    ai_limit_month: float | None = None
    open_alerts: int = 0
    last_activity: datetime | None = None


@dataclass
class SpendDay:
    day: date
    cost: float = 0.0
    runs: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class Overview:
    health: list[HealthDot] = field(default_factory=list)
    workspaces: list[WorkspaceRow] = field(default_factory=list)
    spend: list[SpendDay] = field(default_factory=list)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


# ── health ───────────────────────────────────────────────────────────────────


def _health(session, now: datetime) -> list[HealthDot]:
    from marvin.core.config import get_app_settings

    dots: list[HealthDot] = []
    settings = get_app_settings()

    def safely(fn):
        try:
            dot = fn()
            if dot:
                dots.append(dot)
        except Exception:  # noqa: BLE001 — a dot that can't be read is left out, never the page
            session.rollback()
            logger.debug("overview health dot failed", exc_info=True)

    def backups():
        from marvin.services.backup_health import all_targets

        targets = all_targets(session, now)
        bad = [t for t in targets if t.state not in ("ok", "unknown")]
        if not targets:
            return HealthDot("backups", "No backup targets", OFF, "/admin/backup-health")
        return HealthDot(
            "backups", f"{len(bad)} backup problem{'s' if len(bad) != 1 else ''}" if bad else "Backups ok", BAD if bad else OK, "/admin/backup-health"
        )

    def tasks():
        from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

        failing = (
            session.query(sa.func.count(ScheduledTaskModel.id))
            .filter(ScheduledTaskModel.enabled.is_(True), ScheduledTaskModel.last_status.in_(("failed", "error")))
            .scalar()
            or 0
        )
        return HealthDot(
            "tasks",
            f"{failing} failing task{'s' if failing != 1 else ''}" if failing else "Tasks ok",
            BAD if failing else OK,
            "/admin/scheduled-tasks",
        )

    def alerts():
        from marvin.db.models.groups.integration_errors import IntegrationAlertModel

        open_ = session.query(sa.func.count(IntegrationAlertModel.id)).filter(IntegrationAlertModel.resolved_at.is_(None)).scalar() or 0
        return HealthDot(
            "alerts",
            f"{open_} open integration alert{'s' if open_ != 1 else ''}" if open_ else "No open alerts",
            WARN if open_ else OK,
            "/admin/alerts",
        )

    def unpriced():
        from marvin.db.models.groups.ai_executions import AIExecutionModel as Run

        n = (
            session.query(sa.func.count(Run.id))
            .filter(Run.status == "completed", Run.estimated_cost_usd.is_(None), Run.total_tokens > 0, Run.started_at >= _naive(_month_start(now)))
            .scalar()
            or 0
        )
        return HealthDot("unpriced", f"{n} unpriced AI run{'s' if n != 1 else ''}" if n else "AI runs priced", WARN if n else OK, "/admin/ai-pricing")

    def price_feed():
        from marvin.services.ai.price_feed import status

        st = status(session)
        if not st.get("url"):
            return HealthDot("price_feed", "Price feed off", OFF, "/admin/ai-pricing")
        fetched = st.get("fetched_at")
        when = datetime.fromisoformat(fetched) if isinstance(fetched, str) else fetched
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        stale = st.get("error") or when is None or now - when > timedelta(hours=PRICE_FEED_STALE_HOURS)
        return HealthDot("price_feed", "Price feed stale" if stale else "Price feed fresh", WARN if stale else OK, "/admin/ai-pricing")

    def push():
        ready = bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)
        return HealthDot("push", "Push ready" if ready else "Push off", OK if ready else OFF, "/admin/site-settings")

    def ui_address():
        local = any(h in (settings.BASE_URL or "") for h in ("localhost", "127.0.0.1"))
        return HealthDot("ui_address", "Email links point at localhost" if local else "Email links ok", BAD if local else OK, "/admin/site-settings")

    for check in (backups, tasks, alerts, unpriced, price_feed, push, ui_address):
        safely(check)
    return dots


# ── workspaces ───────────────────────────────────────────────────────────────


def _workspaces(session, now: datetime) -> list[WorkspaceRow]:
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_executions import AIExecutionModel as Run
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel
    from marvin.db.models.platform import Entries
    from marvin.db.models.platform.event_log import EventLogModel

    rows = {str(g.id): WorkspaceRow(id=str(g.id), name=g.name, slug=g.slug) for g in session.query(Groups).all()}

    def per_group(query):
        return {str(gid): value for gid, value in query.all() if str(gid) in rows}

    counts = [
        ("entries", session.query(Entries.group_id, sa.func.count(Entries.id)).group_by(Entries.group_id)),
        (
            "ai_spend_month",
            session.query(Run.group_id, sa.func.coalesce(sa.func.sum(Run.estimated_cost_usd), 0.0))
            .filter(Run.started_at >= _naive(_month_start(now)))
            .group_by(Run.group_id),
        ),
        (
            "open_alerts",
            session.query(IntegrationAlertModel.group_id, sa.func.count(IntegrationAlertModel.id))
            .filter(IntegrationAlertModel.resolved_at.is_(None))
            .group_by(IntegrationAlertModel.group_id),
        ),
        ("last_activity", session.query(EventLogModel.workspace_id, sa.func.max(EventLogModel.occurred_at)).group_by(EventLogModel.workspace_id)),
    ]
    for attr, query in counts:
        try:
            for gid, value in per_group(query).items():
                setattr(rows[gid], attr, round(float(value), 4) if attr == "ai_spend_month" else value)
        except Exception:  # noqa: BLE001 — a column that can't be read stays empty
            session.rollback()
            logger.debug("overview workspace column %s failed", attr, exc_info=True)
    try:
        from marvin.db.models.users.workspace_members import WorkspaceMembers

        members = session.query(WorkspaceMembers.group_id, sa.func.count(WorkspaceMembers.user_id)).group_by(WorkspaceMembers.group_id)
        for gid, n in per_group(members).items():
            rows[gid].members = n
    except Exception:  # noqa: BLE001
        session.rollback()
    try:
        from marvin.services.ai.budget import limits_for

        for gid, cfg in per_group(session.query(WorkspaceAISettingsModel.group_id, WorkspaceAISettingsModel.budget_config)).items():
            rows[gid].ai_limit_month = limits_for(cfg).month_usd
    except Exception:  # noqa: BLE001
        session.rollback()
    return sorted(rows.values(), key=lambda r: r.last_activity or datetime.min.replace(tzinfo=UTC), reverse=True)


# ── AI spend by day ──────────────────────────────────────────────────────────


def _spend(session, now: datetime, days: int = SPEND_DAYS) -> list[SpendDay]:
    from marvin.db.models.groups.ai_executions import AIExecutionModel as Run

    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    by_day = {(start + timedelta(days=i)).date(): SpendDay(day=(start + timedelta(days=i)).date()) for i in range(days)}
    day = sa.func.date(Run.started_at)
    q = (
        session.query(
            day,
            sa.func.coalesce(sa.func.sum(Run.estimated_cost_usd), 0.0),
            sa.func.count(Run.id),
            sa.func.coalesce(sa.func.sum(Run.prompt_tokens), 0),
            sa.func.coalesce(sa.func.sum(Run.cached_prompt_tokens), 0),
        )
        .filter(Run.started_at >= _naive(start))
        .group_by(day)
    )
    for d, cost, runs, prompt, cached in q.all():
        if d in by_day:
            by_day[d] = SpendDay(day=d, cost=round(float(cost), 4), runs=int(runs), prompt_tokens=int(prompt), cached_tokens=int(cached))
    return list(by_day.values())


def overview(session, now: datetime | None = None) -> Overview:
    now = now or datetime.now(UTC)
    out = Overview()
    for attr, fn in (("health", _health), ("workspaces", _workspaces), ("spend", _spend)):
        try:
            setattr(out, attr, fn(session, now))
        except Exception:  # noqa: BLE001 — a part that fails is empty, the rest still shows
            session.rollback()
            logger.warning("admin overview: %s failed", attr, exc_info=True)
    return out
