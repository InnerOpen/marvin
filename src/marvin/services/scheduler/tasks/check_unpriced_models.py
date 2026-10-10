"""Warn when a workspace starts running an AI model that has no price.

A run with no price is stored with no cost, so the monthly cost limit can't see it; before this, such runs
silently counted as $0. Hourly (leader only): for each workspace, provider and model whose first unpriced
run fell in the previous whole clock hour, send ``ai_model_unpriced`` once — the activity toast, and whatever
the workspace's notifications route it to. The AI settings usage card lists this month's unpriced runs.
Never raises.
"""

from datetime import UTC, datetime, timedelta

from marvin.core import root_logger
from marvin.db.db_setup import session_context

logger = root_logger.get_logger(__name__)


def check_unpriced_models(now: datetime | None = None) -> int:
    from marvin.db.models.groups import Groups
    from marvin.services.ai.budget import first_unpriced_between
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventAIBudgetData, EventTypes

    end = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=1)
    try:
        with session_context() as session:
            found = first_unpriced_between(session, start, end)
            names = {g.id: g.name for g in session.query(Groups).filter(Groups.id.in_({f["group_id"] for f in found}))} if found else {}
        bus = EventBusService(bg_tasks=None)
        for f in found:
            detail = (
                f"{f['provider']} model {f['model']} has no price, so its runs don't count toward the AI cost limit. "
                "Set a price for it, or pick a priced model."
            )
            bus.dispatch(
                integration_id="ai_pricing",
                group_id=f["group_id"],
                event_type=EventTypes.ai_model_unpriced,
                document_data=EventAIBudgetData(
                    reason="unpriced_model",
                    provider_type=f["provider"],
                    model_id=f["model"],
                    detail=detail,
                    workspace_id=f["group_id"],
                    workspace_name=names.get(f["group_id"]),
                ),
                message=detail,
            )
        if found:
            logger.info(f"unpriced AI models: {len(found)} newly seen")
        return len(found)
    except Exception as e:  # noqa: BLE001 — the scheduler must keep ticking
        logger.error(f"unpriced model check failed: {e}", exc_info=True)
        return 0
