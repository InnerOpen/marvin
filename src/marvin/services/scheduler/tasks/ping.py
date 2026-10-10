"""
This module defines a simple "ping" task for the Marvin scheduler.

The primary purpose of this task is to provide a basic, lightweight function
that can be scheduled to run periodically, allowing administrators or developers
to verify that the scheduler service is operational by observing the logs.
"""

from marvin.core import root_logger  # Application logger

# Logger instance for this module, typically will inherit the "scheduler" logger if called from there
# or can be configured to be specific like "scheduler.tasks.ping".
logger = root_logger.get_logger(__name__)  # Using __name__ for more specific logger if desired


def ping() -> None:
    """
    A simple scheduled task that logs a "Ping" message at the DEBUG level.

    This function is intended to be registered with the scheduler (e.g., to run
    minutely or hourly) to provide a heartbeat or basic check that scheduled tasks
    are being executed. Its output will appear in the application logs if the
    log level is set to DEBUG or lower.
    """
    logger.debug("🏓 Ping!")
