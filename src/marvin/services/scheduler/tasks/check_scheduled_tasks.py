"""
Scheduled task checker for the Marvin scheduler.

This task runs every minute to find and trigger scheduled tasks that are due for execution.
It emits scheduled_task.triggered events that are handled by the ScheduledTaskListener.
"""

from datetime import UTC, datetime

from marvin.core import root_logger
from marvin.db.db_setup import session_context
from marvin.repos.repository_factory import AllRepositories
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import EventScheduledTaskData, EventTypes

logger = root_logger.get_logger(__name__)


def check_scheduled_tasks() -> None:
    """
    Find and trigger scheduled tasks that are due to run.

    This function:
    1. Queries for tasks with next_run_at <= now and enabled=True
    2. For each due task, emits a scheduled_task.triggered event
    3. The ScheduledTaskListener handles execution
    4. Task state updates (next_run_at) are handled by handlers/listeners

    Runs every minute via SchedulerRegistry.register_minutely().
    """
    try:
        with session_context() as session:
            # System-wide access (group_id=None) to find all tasks
            repos = AllRepositories(session, group_id=None)
            event_bus = EventBusService(bg_tasks=None)

            if scheduled := repos.scheduled_tasks.schedule_unscheduled_cron():
                logger.info(f"Scheduled {scheduled} cron task(s) that had no next run")

            now = datetime.now(UTC)
            due_tasks = repos.scheduled_tasks.get_due_tasks(now)

            if not due_tasks:
                logger.debug("No scheduled tasks due for execution")
                return

            logger.info(f"Found {len(due_tasks)} scheduled task(s) due for execution")

            for task in due_tasks:
                try:
                    # Emit triggered event - ScheduledTaskListener will handle execution
                    event_bus.dispatch(
                        integration_id="scheduled_tasks",
                        group_id=task.group_id,
                        event_type=EventTypes.scheduled_task_triggered,
                        document_data=EventScheduledTaskData.from_model(task),
                        message=f"Scheduled task '{task.name}' triggered at {now.isoformat()}",
                        entity_id=task.id,
                        entity_type="scheduled_task",
                    )

                    logger.debug(f"Triggered scheduled task: {task.name} (id: {task.id})")

                except Exception as e:
                    logger.error(f"Failed to trigger scheduled task {task.name} (id: {task.id}): {e}")
                    # Continue with other tasks even if one fails to trigger

    except Exception as e:
        logger.error(f"Error in check_scheduled_tasks: {e}")
        # Don't raise - scheduler should continue running even if this iteration fails
