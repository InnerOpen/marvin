"""Send the site rebuilds that `request_site_rebuild` queued, once their requests have gone quiet.

Runs on the scheduler's frequent tick (leader only), so each queued rebuild is sent exactly once.
"""

from marvin.core import root_logger
from marvin.db.db_setup import session_context
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.scheduled_tasks.handlers.publishing import dispatch_site_rebuild
from marvin.services.site_rebuild import dispatch_due_rebuilds

logger = root_logger.get_logger(__name__)


def dispatch_site_rebuilds() -> None:
    try:
        event_bus = EventBusService(bg_tasks=None)
        with session_context() as session:
            sent = dispatch_due_rebuilds(session, lambda group_id, reason: dispatch_site_rebuild(group_id, reason, event_bus))
        if sent:
            logger.info("dispatched %d coalesced site rebuild(s)", sent)
    except Exception as e:  # noqa: BLE001 — a scheduler tick must never take the process down
        logger.error(f"dispatching site rebuilds failed: {e}", exc_info=True)
