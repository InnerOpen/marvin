"""
Scheduled tasks service.

This module provides the infrastructure for executing scheduled tasks on a recurring
or one-time basis. Handlers are registered at import time and executed by the
SchedulerService when tasks are due.
"""

# Import handler modules to trigger registration
# Import all handler modules to register them
from .handlers import (  # noqa: F401  — imported for handler registration side effects
    ScheduledTaskHandler,
    TaskHandlerRegistry,
    ai,
    automation,
    integrations,
    maintenance,
    media,
    publishing,
)

__all__ = [
    "ScheduledTaskHandler",
    "TaskHandlerRegistry",
]
