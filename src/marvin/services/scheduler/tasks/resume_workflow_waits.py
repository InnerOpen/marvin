"""Go on with workflow runs whose Wait step's time has come (services/automation/waits.py).

Runs every minute (leader only): each run waiting past its `resume_at` resumes from the next step in a new run.
"""

from marvin.core import root_logger
from marvin.db.db_setup import session_context

logger = root_logger.get_logger(__name__)


def resume_workflow_waits() -> None:
    from marvin.services.automation.waits import resume_due

    try:
        with session_context() as session:
            count = resume_due(session, logger=logger)
        if count:
            logger.info("resumed %d waiting workflow run(s)", count)
    except Exception as e:  # noqa: BLE001 — a scheduler tick must never take the process down
        logger.error(f"resuming waiting workflow runs failed: {e}", exc_info=True)
