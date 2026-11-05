"""Notice a worker that went quiet, or came back (services/worker_health): each becomes a worker_offline / worker_online event.

Runs every scheduler tick (leader only). Never raises: a failed check is logged and the next tick tries again.
"""

from marvin.core import root_logger
from marvin.db.db_setup import session_context

logger = root_logger.get_logger(__name__)


def check_workers() -> None:
    from marvin.services import worker_health

    try:
        with session_context() as session:
            outcome = worker_health.check(session)
        if outcome.offline or outcome.online:
            logger.info(f"worker health: offline {', '.join(outcome.offline) or 'none'}; back online {', '.join(outcome.online) or 'none'}")
    except Exception as e:  # noqa: BLE001 — the scheduler must keep ticking
        logger.error(f"worker health check failed: {e}", exc_info=True)
