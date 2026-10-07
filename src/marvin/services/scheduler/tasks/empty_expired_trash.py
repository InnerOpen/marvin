"""Auto-empty the Trash: delete entries, assets and resources that have been in it longer than their workspace allows.

Runs hourly (leader only — see scheduler/leader.py). Each workspace's limit is its own setting or the
platform default (services/entries/trash.py); "never" skips it. Deleting goes through the normal deletes
(EntryService.delete; services/trash.py delete_asset / delete_resource, which remove an asset's file from
storage), so entry_deleted / asset_deleted / resource_deleted fire per item. Idempotent: an item already gone,
or restored meanwhile, is skipped, so an overlapping run on another replica during a leadership change
deletes nothing twice. Never raises.
"""

from marvin.core import root_logger
from marvin.db.db_setup import session_context
from marvin.services.event_bus_service.event_bus_service import EventBusService

logger = root_logger.get_logger(__name__)


def empty_expired_trash() -> None:
    from marvin.services import trash
    from marvin.services.entries import trash as entry_trash

    for label, purge in (("entries", entry_trash.purge_expired), ("assets/resources", trash.purge_expired)):
        try:
            with session_context() as session:
                purged = purge(session, event_bus=EventBusService(bg_tasks=None))
            if purged:
                logger.info(f"trash auto-empty: {sum(purged.values())} {label} deleted across {len(purged)} workspace(s)")
        except Exception as e:  # noqa: BLE001 — the scheduler must keep ticking
            logger.error(f"trash auto-empty ({label}) failed: {e}", exc_info=True)
