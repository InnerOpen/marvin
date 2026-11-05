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
#: ``trigger_type`` of a run that is an integration's own call (ElevenLabs speech, an image service), not the workspace's AI. They are logged
#: in AI executions with the provider's name, but the limits and totals here are for the AI set up in AI settings, so they leave them out.
INTEGRATION_TRIGGERS = ("capability", "integration")


def ai_runs(query, model):
    """`query` narrowed to the workspace's own AI runs: an integration's calls (``INTEGRATION_TRIGGERS``) are not in its total or its limits."""
    return query.filter(model.trigger_type.notin_(INTEGRATION_TRIGGERS))


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
    integrations: list[dict] = field(default_factory=list)
    """This month's calls to integrations that bill in their own units (ElevenLabs characters): `integration_tally`. Not in any total above."""
    unpriced: list[dict] = field(default_factory=list)
    """This month's completed runs with no price, per provider and model: their cost is unknown, so the monthly
    limit can't see it ({provider, model, runs, tokens})."""

    @property
    def unpriced_runs(self) -> int:
        return sum(u["runs"] for u in self.unpriced)

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


# How the workspace's agents behave, set beside its spend limits in budget_config (AI Settings → Usage & Limits):
# key → (default, lowest, highest). A missing value is the default; one out of range is trimmed to the nearest bound
# (asking for more steps than the platform allows gives the most it allows, never fewer). agent_max_steps defaults
# to the platform's AI_AGENT_MAX_STEPS and its highest is AI_AGENT_MAX_STEPS_CAP.
AGENT_LIMITS: dict[str, tuple[int | None, int, int]] = {
    "agent_max_steps": (None, 1, 50),
    "history_turns": (10, 2, 50),
    "bulk_ask_threshold": (20, 1, 1000),
}


def agent_limit(session, group_id, key: str) -> int:
    """One of AGENT_LIMITS for this workspace."""
    from marvin.core.config import get_app_settings
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    default, low, high = AGENT_LIMITS[key]
    app = get_app_settings()
    if key == "agent_max_steps":
        default, high = app.AI_AGENT_MAX_STEPS, min(high, app.AI_AGENT_MAX_STEPS_CAP)
    row = session.query(WorkspaceAISettingsModel.budget_config).filter_by(group_id=group_id).scalar() if group_id else None
    value = _positive((row or {}).get(key), int)
    if value is None:
        return min(int(default), high)
    return max(low, min(value, high))


def tools_on_demand_enabled(session, group_id) -> bool:
    """Whether this workspace's all-tools agents load rarely used tools only when needed (budget_config
    `load_tools_on_demand`, on unless set false). Off sends every tool with every question, as before."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    cfg = session.query(WorkspaceAISettingsModel.budget_config).filter_by(group_id=group_id).scalar() if group_id else None
    return (cfg or {}).get("load_tools_on_demand") is not False


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
        ai_runs(session.query(func.sum(AIExecutionModel.estimated_cost_usd)), AIExecutionModel)
        .filter(
            AIExecutionModel.group_id == group_id,
            AIExecutionModel.created_at >= _month_start(now),
            AIExecutionModel.status == "completed",
        )
        .scalar()
        or 0.0
    )


def unpriced(session, group_id, now: datetime | None = None) -> list[dict]:
    """This month's completed runs that used tokens but have no price (no price for that provider/model anywhere),
    most runs first. A self-hosted provider's runs cost 0, not nothing, so they aren't here."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel as Run

    now = now or datetime.now(UTC)
    rows = (
        ai_runs(session.query(Run.provider_type, Run.model_id, func.count(Run.id), func.coalesce(func.sum(Run.total_tokens), 0)), Run)
        .filter(
            Run.group_id == group_id,
            Run.created_at >= _month_start(now),
            Run.status == "completed",
            Run.estimated_cost_usd.is_(None),
            Run.total_tokens > 0,
        )
        .group_by(Run.provider_type, Run.model_id)
        .all()
    )
    found = [{"provider": p, "model": m, "runs": int(n), "tokens": int(t)} for p, m, n, t in rows]
    return sorted(found, key=lambda u: (-u["runs"], u["provider"], u["model"]))


def integration_tally(session, group_id, now: datetime | None = None) -> list[dict]:
    """This month's completed integration calls, per provider and unit: {provider, unit, calls, units, billed}. ``units`` is what the call used
    (characters of text); ``billed`` is that times the model's multiplier when the provider reported one (ElevenLabs: some models cost half a
    character per character). No dollars: Marvin cannot know a plan's price, so this is a tally to read against the provider's own meter."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel as Run

    now = now or datetime.now(UTC)
    rows = (
        session.query(Run.provider_type, Run.metadata_json)
        .filter(Run.group_id == group_id, Run.created_at >= _month_start(now), Run.status == "completed", Run.trigger_type.in_(INTEGRATION_TRIGGERS))
        .all()
    )
    tally: dict[tuple[str, str], dict] = {}
    for provider, meta in rows:
        meta = meta or {}
        unit = str(meta.get("unit") or "calls")
        entry = tally.setdefault((provider, unit), {"provider": provider, "unit": unit, "calls": 0, "units": 0, "billed": 0.0})
        used = int(meta.get("units") or 0)
        entry["calls"] += 1
        entry["units"] += used
        entry["billed"] += used * float(meta.get("multiplier") or 1.0)
    return sorted(tally.values(), key=lambda t: (-t["calls"], t["provider"], t["unit"]))


def first_unpriced_between(session, start: datetime, end: datetime) -> list[dict]:
    """(workspace, provider, model) whose first unpriced run (within the execution log's retention) falls in
    [start, end): the models that just started running with no price. Used by the hourly check, which looks at
    the previous whole hour, so each one is reported once."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel as Run

    first = func.min(Run.created_at)
    rows = (
        ai_runs(session.query(Run.group_id, Run.provider_type, Run.model_id, first), Run)
        .filter(Run.status == "completed", Run.estimated_cost_usd.is_(None), Run.total_tokens > 0)
        .group_by(Run.group_id, Run.provider_type, Run.model_id)
        .having(first >= start, first < end)
        .all()
    )
    return [{"group_id": g, "provider": p, "model": m} for g, p, m, _ in rows]


def runs_today(session, group_id, now: datetime | None = None) -> int:
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    now = now or datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        ai_runs(session.query(func.count(AIExecutionModel.id)), AIExecutionModel)
        .filter(AIExecutionModel.group_id == group_id, AIExecutionModel.created_at >= today)
        .scalar()
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
        ai_runs(
            session.query(
                AIExecutionModel.operation_slug,
                func.count(AIExecutionModel.id),
                func.coalesce(func.sum(AIExecutionModel.total_tokens), 0),
                func.coalesce(func.sum(AIExecutionModel.estimated_cost_usd), 0.0),
            ),
            AIExecutionModel,
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
        unpriced=unpriced(session, group_id, now),
        integrations=integration_tally(session, group_id, now),
    )
