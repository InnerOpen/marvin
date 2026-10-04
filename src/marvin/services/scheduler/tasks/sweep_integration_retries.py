"""Run the integration retries that are due — the durable half of an integration's error policy.

A failed workflow step whose provider asked for a retry waits in ``integration_retries``. Every
scheduler tick (60s, leader only) this claims the due rows, resumes each run at its failed step
(`engine.run_retry`: the entry is re-read and the workflow's conditions re-checked first), and prunes
retry history and resolved alerts older than 30 days.

A scheduler tick rather than a scheduled-task row: a task row's interval is re-armed after each run,
so a 60s task fires about every other tick, and it would add a run-log row a minute.
"""

from marvin.core import root_logger
from marvin.db.db_setup import session_context

logger = root_logger.get_logger(__name__)


def sweep_integration_retries() -> None:
    try:
        from marvin.services.automation.engine import run_retry
        from marvin.services.automation.recorder import ExecutionRecorder
        from marvin.services.integrations import errors

        outcomes: dict[str, int] = {}
        with session_context() as session:
            for row in errors.claim_due(session):
                try:
                    outcome = run_retry(session, row.group_id, row, logger=logger, recorder=ExecutionRecorder(session, row.group_id))
                except Exception as e:  # noqa: BLE001 — one broken retry must not stall the rest
                    session.rollback()
                    logger.error(f"integration retry {row.id} failed to run: {e}", exc_info=True)
                    errors.retry_failed_plainly(session, row, f"the retry could not run: {e}")
                    outcome = "error"
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
            pruned = errors.prune(session)
        if outcomes:
            logger.info("integration retries: %s", ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items())))
        if pruned:
            logger.info("pruned %d old integration retries/alerts", pruned)
    except Exception as e:  # noqa: BLE001 — a scheduler tick must never take the process down
        logger.error(f"sweeping integration retries failed: {e}", exc_info=True)
