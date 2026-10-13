"""Settle workflow approvals nobody decided in time as `expired` — and let their runs go on.

Runs hourly (leader only). Each run waiting past its approval step's `expires_in_hours` resumes from the next step
with `${steps.<id>.output.decision}` = expired (services/automation/approvals.py), so a workflow can act on it.
"""

from marvin.core import root_logger
from marvin.db.db_setup import session_context

logger = root_logger.get_logger(__name__)


def expire_workflow_approvals() -> None:
    from marvin.services.automation.approvals import expire_due

    try:
        with session_context() as session:
            count = expire_due(session, logger=logger)
        if count:
            logger.info("expired %d workflow approval(s)", count)
    except Exception as e:  # noqa: BLE001 — a scheduler tick must never take the process down
        logger.error(f"expiring workflow approvals failed: {e}", exc_info=True)
