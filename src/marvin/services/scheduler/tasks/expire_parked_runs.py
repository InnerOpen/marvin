"""End agent runs that waited for approval longer than AI_PARKED_RUN_TTL_HOURS.

Runs hourly (leader only). Each expired park — with its specialists' parks — is denied, its executions
failed "expired", and approval_rejected fires on the root with reason "expired" (no notification yet).
"""

from marvin.core import root_logger
from marvin.core.config import get_app_settings
from marvin.db.db_setup import session_context
from marvin.services.ai.parked_runs import REASON_EXPIRED, approval_event_data, approval_message
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import EventTypes

logger = root_logger.get_logger(__name__)


def expire_parked_runs() -> None:
    from marvin.services.ai.parked_runs import expire_parked_runs as _expire

    try:
        ttl = int(get_app_settings().AI_PARKED_RUN_TTL_HOURS or 0)
        if ttl <= 0:
            return
        event_bus = EventBusService(bg_tasks=None)

        def emit(root, calls, execution) -> None:
            decisions = {str(c.get("id")): "deny" for c in calls}
            try:
                event_bus.dispatch(
                    integration_id="ai_operations",
                    group_id=root.group_id,
                    event_type=EventTypes.approval_rejected,
                    document_data=approval_event_data(root, execution, calls, decisions, reason=REASON_EXPIRED),
                    message=approval_message(EventTypes.approval_rejected, root.agent_slug, calls, REASON_EXPIRED),
                    user_id=root.created_by,
                    entity_id=root.id,
                    entity_type="ai_thread",
                )
            except Exception as e:  # noqa: BLE001 — the record is best-effort; the park is already ended
                logger.error(f"approval_rejected (expired) dispatch failed: {e}", exc_info=True)

        with session_context() as session:
            count = _expire(session, ttl, emit)
        if count:
            logger.info("expired %d parked agent run(s)", count)
    except Exception as e:  # noqa: BLE001 — a scheduler tick must never take the process down
        logger.error(f"expiring parked agent runs failed: {e}", exc_info=True)
