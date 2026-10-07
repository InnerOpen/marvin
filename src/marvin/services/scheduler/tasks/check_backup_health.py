"""Announce backup runs and notice a backup target that went quiet (services/backup_health).

Runs every scheduler tick (leader only): each run a backup CronJob recorded becomes backup_completed or
backup_failed, and a target with no successful run inside its window gets one backup_failed (reason
overdue) per incident. Never raises: a failed check is logged and the next tick tries again.
"""

from marvin.core import root_logger
from marvin.db.db_setup import session_context
from marvin.services.event_bus_service.event_bus_service import EventBusService

logger = root_logger.get_logger(__name__)


def check_backup_health() -> None:
    from marvin.services import backup_health

    try:
        with session_context() as session:
            outcome = backup_health.check(session, EventBusService(bg_tasks=None))
        if outcome.announced or outcome.overdue or outcome.pruned:
            logger.info(
                f"backup health: {outcome.announced} run(s) announced, overdue: {', '.join(outcome.overdue) or 'none'}, "
                f"{outcome.pruned} old run(s) pruned"
            )
    except Exception as e:  # noqa: BLE001 — the scheduler must keep ticking
        logger.error(f"backup health check failed: {e}", exc_info=True)
