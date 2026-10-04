"""Action executors for Flavor B automations.

Importing this package registers every executor (side-effect imports below). The engine calls
:func:`run_action` to dispatch by kind; :func:`available_kinds` drives the builder's options.
"""

# Register executors (import for side effects).
from . import emit_event, entry, handler, integration, operation, webhook  # noqa: E402,F401
from .base import ACTION_EXECUTORS, AutomationActionError, IntegrationStepError, available_kinds, register_action, run_action

__all__ = [
    "ACTION_EXECUTORS",
    "AutomationActionError",
    "IntegrationStepError",
    "available_kinds",
    "register_action",
    "run_action",
]
