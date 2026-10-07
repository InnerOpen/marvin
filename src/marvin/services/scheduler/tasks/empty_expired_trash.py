"""Auto-empty the Trash: delete entries that have been in it longer than their workspace allows.

Runs hourly (leader only — see scheduler/leader.py). Each workspace's limit is its own setting or the
platform default (services/entries/trash.py); "never" skips it. Deleting goes through EntryService.delete,
so entry_deleted fires per entry. Idempotent: an entry already gone, or restored meanwhile, is skipped, so
an overlapping run on another replica during a leadership change deletes nothing twice. Never raises.
"""

from marvin.core import root_logger
from marvin.db.db_setup import session_context
from marvin.services.event_bus_service.event_bus_service import EventBusService

logger = root_logger.get_logger(__name__)


def empty_expired_trash() -> None:
    from marvin.services.entries.trash import purge_expired

    try:
        with session_context() as session:
            purged = purge_expired(session, event_bus=EventBusService(bg_tasks=None))
        if purged:
            logger.info(f"trash auto-empty: {sum(purged.values())} entries deleted across {len(purged)} workspace(s)")
    except Exception as e:  # noqa: BLE001 — the scheduler must keep ticking
        logger.error(f"trash auto-empty failed: {e}", exc_info=True)
