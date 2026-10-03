"""A workspace's AI limits and where it stands against them.

One place for the numbers, so the gate that refuses a call, the warning events and the usage card in
AI settings always agree. Limits live in `WorkspaceAISettingsModel.budget_config`:

- `max_cost_per_month_usd` — estimated spend on completed runs since the 1st (UTC); at the limit new
  runs are refused, and crossing `AI_BUDGET_WARNING_PERCENT` of it fires a warning event;
- `max_requests_per_day` — runs started since midnight (UTC), whatever their outcome;
- `max_tokens_per_request` — the output-token cap per model call.

Costs are estimates from the pricing table (embedding calls for search are not counted — they cost a
fraction of a cent per reindex). The provider's own account balance is not visible to Marvin; a
provider that runs out says so in the call's error, which fires `ai_provider_quota_exceeded`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import func

logger = logging.getLogger(__name__)

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_OVER = "over"
TOP_OPERATIONS = 8
# The bubble stored its main-agent runs as bare "agent" until 2026-10-03; they are the same agent.
LEGACY_OPERATIONS = {"agent": "agent:marvin"}


@dataclass(frozen=True)
class Limits:
    month_usd: float | None = None
    per_day: int | None = None
    tokens_per_request: int | None = None


@dataclass
class Usage:
    limits: Limits
    warning_percent: float
    month_cost_usd: float = 0.0
    month_tokens: int = 0
    month_runs: int = 0
    today_runs: int = 0
    resets_on: date | None = None
    by_operation: list[dict] = field(default_factory=list)

    @property
    def month_percent(self) -> float | None:
        return _percent(self.month_cost_usd, self.limits.month_usd)

    @property
    def day_percent(self) -> float | None:
        return _percent(self.today_runs, self.limits.per_day)

    @property
    def level(self) -> str:
        """The worst of the two limits: over at 100 %, warn from the warning percent."""
        worst = max((p for p in (self.month_percent, self.day_percent) if p is not None), default=None)
        if worst is None:
            return LEVEL_OK
        if worst >= 100:
            return LEVEL_OVER
        return LEVEL_WARN if 0 < self.warning_percent <= worst else LEVEL_OK


def _percent(value: float, limit: float | None) -> float | None:
    return round(value / limit * 100, 1) if limit else None


def _positive(raw, kind):
    try:
        value = kind(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def limits_for(budget_config: dict | None) -> Limits:
    """The configured limits; a missing, non-numeric or non-positive value means no limit."""
    cfg = budget_config or {}
    return Limits(
        month_usd=_positive(cfg.get("max_cost_per_month_usd"), float),
        per_day=_positive(cfg.get("max_requests_per_day"), int),
        tokens_per_request=_positive(cfg.get("max_tokens_per_request"), int),
    )


def workspace_limits(session, group_id) -> Limits:
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    return limits_for(settings.budget_config if settings else None)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(now: datetime) -> date:
    return date(now.year + now.month // 12, now.month % 12 + 1, 1)


def month_spend(session, group_id, now: datetime | None = None) -> float:
    """Estimated spend on completed runs this month — what the monthly limit is measured against."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    now = now or datetime.now(UTC)
    return float(
        session.query(func.sum(AIExecutionModel.estimated_cost_usd))
        .filter(
            AIExecutionModel.group_id == group_id,
            AIExecutionModel.created_at >= _month_start(now),
            AIExecutionModel.status == "completed",
        )
        .scalar()
        or 0.0
    )


def runs_today(session, group_id, now: datetime | None = None) -> int:
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    now = now or datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        session.query(func.count(AIExecutionModel.id)).filter(AIExecutionModel.group_id == group_id, AIExecutionModel.created_at >= today).scalar()
        or 0
    )


def blocked_reason(session, group_id, now: datetime | None = None) -> str | None:
    """Why a new AI run must be refused right now, or None when it may go ahead."""
    limits = workspace_limits(session, group_id)
    if limits.per_day and runs_today(session, group_id, now) >= limits.per_day:
        return f"Daily request limit ({limits.per_day}) reached."
    if limits.month_usd and month_spend(session, group_id, now) >= limits.month_usd:
        return f"Monthly cost limit (${limits.month_usd:.2f}) reached."
    return None


def max_output_tokens(session, group_id) -> int | None:
    """The per-call output-token cap: the workspace's, else the app default."""
    from marvin.core.config import get_app_settings

    return workspace_limits(session, group_id).tokens_per_request or getattr(get_app_settings(), "AI_DEFAULT_MAX_TOKENS", None)


def warning_percent() -> float:
    from marvin.core.config import get_app_settings

    return float(getattr(get_app_settings(), "AI_BUDGET_WARNING_PERCENT", 80.0))


@dataclass(frozen=True)
class Crossing:
    exceeded: bool
    spent: float
    limit: float
    percent: float
    detail: str


def crossing_after(session, group_id, run_cost: float | None) -> Crossing | None:
    """The monthly line this run's cost just crossed — the limit, else the warning — or None.

    Fires on the one run that crosses, so each line is announced once a month.
    """
    limit = workspace_limits(session, group_id).month_usd
    if not limit:
        return None
    spent = month_spend(session, group_id)
    before = spent - (run_cost or 0.0)
    warn = warning_percent() / 100.0
    if before < limit <= spent:
        return Crossing(True, spent, limit, 100.0, f"Monthly AI cost limit of ${limit:.2f} reached (spent ${spent:.2f})")
    if warn > 0 and before < warn * limit <= spent:
        pct = round(spent / limit * 100, 1)
        return Crossing(False, spent, limit, pct, f"AI spend reached {round(pct)}% of the ${limit:.2f} monthly limit")
    return None


def emit_crossing(group_id, crossing: Crossing, *, user_id=None, source: str = "ai_operations") -> None:
    """Dispatch the crossing as ai_budget_exceeded / ai_budget_threshold_reached (for runs outside a request)."""
    from marvin.db.db_setup import session_context
    from marvin.db.models.groups.groups import Groups
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventAIBudgetData, EventTypes

    try:
        with session_context() as session:
            group = session.get(Groups, group_id)
            name = group.name if group else None
        EventBusService(bg_tasks=None).dispatch(
            integration_id=source,
            group_id=group_id,
            event_type=EventTypes.ai_budget_exceeded if crossing.exceeded else EventTypes.ai_budget_threshold_reached,
            document_data=EventAIBudgetData(
                reason="monthly_cost",
                current_value=crossing.spent,
                limit_value=crossing.limit,
                percent=crossing.percent,
                detail=crossing.detail,
                workspace_id=group_id,
                workspace_name=name,
            ),
            message=crossing.detail,
            user_id=user_id,
        )
    except Exception as e:  # noqa: BLE001 — a warning must never fail the run that triggered it
        logger.error("failed to dispatch the AI budget event for %s: %s", group_id, e, exc_info=True)


def usage(session, group_id, now: datetime | None = None) -> Usage:
    """This month and today against the limits, with the operations that cost the most this month."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    now = now or datetime.now(UTC)
    since = _month_start(now)
    rows = (
        session.query(
            AIExecutionModel.operation_slug,
            func.count(AIExecutionModel.id),
            func.coalesce(func.sum(AIExecutionModel.total_tokens), 0),
            func.coalesce(func.sum(AIExecutionModel.estimated_cost_usd), 0.0),
        )
        .filter(AIExecutionModel.group_id == group_id, AIExecutionModel.created_at >= since)
        .group_by(AIExecutionModel.operation_slug)
        .all()
    )
    merged: dict[str, dict] = {}
    for slug, n, t, c in rows:
        slug = LEGACY_OPERATIONS.get(slug, slug)
        op = merged.setdefault(slug, {"operation": slug, "runs": 0, "tokens": 0, "cost_usd": 0.0})
        op["runs"] += int(n)
        op["tokens"] += int(t or 0)
        op["cost_usd"] += float(c or 0.0)
    ops = sorted(merged.values(), key=lambda o: (o["cost_usd"], o["tokens"]), reverse=True)
    return Usage(
        limits=workspace_limits(session, group_id),
        warning_percent=warning_percent(),
        month_cost_usd=month_spend(session, group_id, now),
        month_tokens=sum(o["tokens"] for o in ops),
        month_runs=sum(o["runs"] for o in ops),
        today_runs=runs_today(session, group_id, now),
        resets_on=_next_month(now),
        by_operation=ops[:TOP_OPERATIONS],
    )
