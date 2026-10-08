"""The day-before reminder for the Trash's auto-empty: what will be deleted forever within a day.

Runs hourly (leader only — see scheduler/leader.py), after empty_expired_trash. For each workspace whose
auto-empty isn't "never" and that has entries, assets or resources due within 24 hours, it fires
``trash_auto_empty_soon`` once that day (``group_preferences.trash_reminded_on``, claimed atomically, so another
replica or a later tick the same day sends nothing): its owners and admins get a push (Profile → Notifications →
Trash reminders), and the workspace's notifications send it where they say (off by default). Never raises.
"""

from marvin.core import root_logger
from marvin.db.db_setup import session_context
from marvin.services.event_bus_service.event_bus_service import EventBusService

logger = root_logger.get_logger(__name__)


def remind_trash_auto_empty() -> None:
    from marvin.services import trash

    try:
        with session_context() as session:
            reminded = trash.remind_auto_empty(session, event_bus=EventBusService(bg_tasks=None))
        if reminded:
            logger.info(f"trash reminder: {len(reminded)} workspace(s) reminded ({sum(reminded.values())} item(s) due within a day)")
    except Exception as e:  # noqa: BLE001 — the scheduler must keep ticking
        logger.error(f"trash reminder failed: {e}", exc_info=True)
