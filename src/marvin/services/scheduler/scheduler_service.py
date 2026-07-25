"""
This module implements the scheduler service for the Marvin application.

It defines the `SchedulerService` class responsible for starting and managing
periodically executed tasks. Tasks (callbacks) are registered via the
`SchedulerRegistry` and are run at specified intervals (minutely, hourly, daily)
using the `repeat_every` decorator from `marvin.services.scheduler.runner`.

The daily tasks have special handling to ensure they run at a specific configured
time of day (UTC).
"""

import asyncio  # For asynchronous operations and task scheduling
from collections.abc import Callable  # For type hinting callables
from datetime import UTC, datetime, timedelta  # For time calculations
from pathlib import Path  # For path operations (CWD)

# Marvin core components and utilities
from marvin.core import root_logger
from marvin.core.config import get_app_settings
from marvin.services.scheduler.runner import repeat_every  # Decorator for periodic tasks

from .leader import acquire_or_renew  # Leader election — only one process may run a tick
from .scheduler_registry import SchedulerRegistry  # Central registry for scheduled functions

# Logger instance for this module
logger = root_logger.get_logger("scheduler")


def _is_leader() -> bool:
    """Whether this process holds the scheduler lease and may run the callbacks.

    Checked once per tick rather than per callback, so a batch either runs whole or not at all.
    A failure to reach the database is treated as "not the leader": skipping a tick is recoverable,
    while every replica assuming leadership is what this exists to prevent.
    """
    from marvin.db.db_setup import session_context

    try:
        with session_context() as session:
            return acquire_or_renew(session, ttl_seconds=get_app_settings().SCHEDULER_LEASE_TTL_SECONDS)
    except Exception as e:  # noqa: BLE001 — a scheduler tick must never take the process down
        logger.error(f"scheduler leader election failed, skipping tick: {e}", exc_info=True)
        return False

# Current working directory of this file (not actively used in this module's logic)
CWD = Path(__file__).parent

# Constants for intervals in minutes
MINUTES_DAY = 1440  # Number of minutes in a day (24 * 60)
MINUTES = 1  # 1 minute interval
MINUTES_HOUR = 60  # Number of minutes in an hour


class SchedulerService:
    """
    Service class responsible for initiating and managing scheduled tasks.

    The `start` method is the main entry point to begin the execution of
    minutely, hourly, and daily scheduled tasks. These tasks are defined
    elsewhere and registered with the `SchedulerRegistry`.
    """

    @staticmethod
    async def start() -> None:
        """
        Starts the scheduler service.

        This method initiates the periodic execution of tasks registered for
        minutely and hourly frequencies immediately (though `wait_first=True`
        for hourly and minutely means they wait for the first interval).
        It also schedules the daily tasks to run at a specific configured time.
        """
        logger.info("SchedulerService starting...")
        # Start minutely and hourly tasks.
        # `run_minutely` and `run_hourly` are decorated with `repeat_every`.
        # Calling them here effectively schedules their first execution and subsequent repeats.
        # `wait_first=True` in their decorators means they will wait for the first interval.
        await run_minutely()  # Initial call to start the minutely repeating task loop
        await run_hourly()  # Initial call to start the hourly repeating task loop

        # Schedule the daily tasks.
        # `schedule_daily` calculates the delay until the next configured daily run time
        # and then calls `run_daily`. This is created as an asyncio task to run concurrently.
        logger.info("Scheduling daily tasks...")
        asyncio.create_task(schedule_daily())
        logger.info("SchedulerService started and daily tasks scheduled.")


async def schedule_daily() -> None:
    """
    Calculates the delay until the next configured daily run time and schedules `run_daily`.

    This function determines the UTC time for the next daily task execution based on
    `DAILY_SCHEDULE_TIME_UTC` from application settings. It then sleeps until that
    time and calls `run_daily` to execute all registered daily tasks.
    This function itself is intended to be run once at startup via `asyncio.create_task`.
    The `run_daily` function, once called, will then repeat every 24 hours.
    """
    now_utc = datetime.now(UTC)  # Current UTC time
    daily_schedule_setting = get_app_settings().DAILY_SCHEDULE_TIME_UTC  # Configured H:M for daily tasks (UTC)

    logger.info(
        f"Current UTC time is {now_utc}. Configured DAILY_SCHEDULE_TIME_UTC is {daily_schedule_setting.hour:02d}:{daily_schedule_setting.minute:02d}."
    )

    # Calculate the next scheduled run time for today
    next_run_datetime_utc = now_utc.replace(hour=daily_schedule_setting.hour, minute=daily_schedule_setting.minute, second=0, microsecond=0)

    # Calculate the time difference (delta) to the next schedule
    time_delta_to_next_run = next_run_datetime_utc - now_utc

    # If the calculated next run time for today has already passed, schedule it for tomorrow
    if time_delta_to_next_run < timedelta(0):  # If delta is negative
        next_run_datetime_utc += timedelta(days=1)
        time_delta_to_next_run = next_run_datetime_utc - now_utc  # Recalculate delta

    # Log time remaining until the next daily run
    total_seconds_to_wait = time_delta_to_next_run.total_seconds()
    hours_until, remainder_seconds = divmod(total_seconds_to_wait, 3600)
    minutes_until, seconds_remainder_final = divmod(remainder_seconds, 60)

    logger.info(f"Time until next daily task execution: {int(hours_until):02d}h:{int(minutes_until):02d}m:{round(seconds_remainder_final):02d}s")
    logger.info(f"Daily tasks will run next at {next_run_datetime_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Wait until the calculated next run time
    await asyncio.sleep(total_seconds_to_wait)

    # Execute the daily tasks for the first time.
    # `run_daily` is decorated with `repeat_every` which will handle subsequent daily runs.
    logger.info(f"Executing initial daily tasks at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    await run_daily()


def _scheduled_task_wrapper(task_callable: Callable[[], None]) -> None:  # Renamed callable to task_callable
    """
    A wrapper function to execute a scheduled task (callback) and handle exceptions.

    This ensures that if a registered scheduled task raises an exception, the error
    is logged, but it does not stop the scheduler service itself or other scheduled tasks.

    Args:
        task_callable (Callable[[], None]): The scheduled function to execute.
                                            It should take no arguments and return None.
    """
    try:
        task_name = getattr(task_callable, "__name__", repr(task_callable))
        logger.debug(f"Executing scheduled task: {task_name}")
        task_callable()  # Execute the registered callback
        logger.debug(f"Finished scheduled task: {task_name}")
    except Exception as e:
        # Log any exception that occurs during the task's execution.
        task_name_for_error = getattr(task_callable, "__name__", "unknown_task")
        logger.error(f"Error in scheduled task func='{task_name_for_error}': exception='{e}'", exc_info=True)


@repeat_every(minutes=MINUTES_DAY, wait_first=False, logger=logger)  # Runs daily; first run is triggered by schedule_daily
async def run_daily() -> None:  # Made async to align with await in schedule_daily
    """
    Executes all registered daily tasks.

    This function is decorated with `@repeat_every` to run once per day.
    The first execution is triggered by `schedule_daily` after waiting for the
    configured daily run time. Subsequent runs are handled by the decorator.
    It iterates through callbacks registered in `SchedulerRegistry._daily`
    and executes them using `_scheduled_task_wrapper`.
    """
    current_time_utc = datetime.now(UTC)
    next_run_time = current_time_utc + timedelta(minutes=MINUTES_DAY)
    logger.info(
        f"Running daily callbacks at {current_time_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}. "
        f"Next run approx: {next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )
    if not _is_leader():
        logger.debug("Not the scheduler leader — skipping daily callbacks.")
        return

    for registered_func in SchedulerRegistry._daily:
        _scheduled_task_wrapper(registered_func)
    logger.info("Finished processing daily callbacks.")


@repeat_every(minutes=MINUTES_HOUR, wait_first=True, logger=logger)
async def run_hourly() -> None:  # Made async as repeat_every can handle it
    """
    Executes all registered hourly tasks.

    Decorated with `@repeat_every` to run once per hour. `wait_first=True` means
    it waits for one hour before the first execution after service start.
    It iterates through `SchedulerRegistry._hourly` callbacks.
    """
    current_time_utc = datetime.now(UTC)
    next_run_time = current_time_utc + timedelta(minutes=MINUTES_HOUR)
    logger.info(
        f"Running hourly callbacks at {current_time_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}. "
        f"Next run approx: {next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )
    if not _is_leader():
        logger.debug("Not the scheduler leader — skipping hourly callbacks.")
        return

    for registered_func in SchedulerRegistry._hourly:
        _scheduled_task_wrapper(registered_func)
    logger.info("Finished processing hourly callbacks.")


@repeat_every(minutes=MINUTES, wait_first=True, logger=logger)
async def run_minutely() -> None:  # Made async
    """
    Executes all registered minutely tasks (currently set for every 5 minutes).

    Decorated with `@repeat_every` to run at `MINUTES` intervals.
    `wait_first=True` means it waits for the initial interval before the first run.
    It iterates through `SchedulerRegistry._minutely` callbacks.
    """
    current_time_utc = datetime.now(UTC)
    next_run_time = current_time_utc + timedelta(minutes=MINUTES)
    logger.info(
        f" {MINUTES} mins) callbacks at {current_time_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}. "
        f"Next run approx: {next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )
    if not _is_leader():
        logger.debug("Not the scheduler leader — skipping minutely callbacks.")
        return

    for registered_func in SchedulerRegistry._minutely:
        _scheduled_task_wrapper(registered_func)
    logger.info(f"Finished processing minutely (every {MINUTES} mins) callbacks.")
