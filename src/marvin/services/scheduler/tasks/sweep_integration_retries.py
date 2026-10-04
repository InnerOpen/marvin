"""Run the integration retries that are due — the durable half of an integration's error policy.

A failed workflow step whose provider asked for a retry waits in ``integration_retries``. Every
scheduler tick (60s, leader only) this claims due rows one at a time, resumes each run at its failed
step (`engine.run_retry`: the entry is re-read and the workflow's conditions re-checked first), moves
parked rows whose connection has no open alert back to pending, and prunes retry history and resolved
alerts older than 30 days.

The work runs in a worker thread, not on the event loop (a retry calls a remote API), and a tick stops
claiming after TICK_BUDGET_S: whatever is left stays pending for the next tick.

A scheduler tick rather than a scheduled-task row: a task row's interval is re-armed after each run,
so a 60s task fires about every other tick, and it would add a run-log row a minute.
"""

import time

from starlette.concurrency import run_in_threadpool

from marvin.core import root_logger
from marvin.db.db_setup import session_context

logger = root_logger.get_logger(__name__)

TICK_BUDGET_S = 40.0  # stop claiming after this long; the tick is every 60s


async def sweep_integration_retries() -> None:
    await run_in_threadpool(sweep_once)


def sweep_once(budget_s: float = TICK_BUDGET_S) -> dict[str, int]:
    """One sweep tick. Returns how many retries ended which way (for logs and tests)."""
    outcomes: dict[str, int] = {}
    try:
        from marvin.services.automation.engine import run_retry
        from marvin.services.automation.recorder import ExecutionRecorder
        from marvin.services.integrations import errors

        deadline = time.monotonic() + budget_s
        with session_context() as session:
            errors.rearm_orphaned_parked(session)
            while time.monotonic() < deadline and (row := errors.claim_next(session)) is not None:
                if row.attempt > row.max_attempts:
                    # Reclaimed after its lease ran out once too often: the run keeps dying mid-way.
                    errors.retry_failed_plainly(session, row, "the retry kept failing to finish (the process stopped mid-run)")
                    outcome = "crashed"
                else:
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
    return outcomes
