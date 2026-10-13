"""
This module defines scheduled tasks related to posting webhooks within the
Marvin application.

It includes functions to:
- Periodically trigger webhook events for all groups or a specific group based
  on their scheduled times (`post_group_webhooks`).
- Trigger a single, specific webhook, often used for testing purposes
  (`post_single_webhook`).

These functions typically interact with the event bus system to dispatch
`webhook_task` events, which are then handled by the `WebhookEventListener`.
"""

import json
from datetime import UTC, datetime  # For datetime operations
from pathlib import Path

from pydantic import UUID4  # For UUID type hinting

from marvin.core.config import get_app_dirs

# Marvin core components and utilities
from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context  # Context manager for DB sessions
from marvin.repos.all_repositories import get_repositories  # Factory for AllRepositories
from marvin.schemas.group.webhook import WebhookRead  # Pydantic schema for webhook data
from marvin.schemas.response.pagination import PaginationQuery  # For fetching all groups
from marvin.services.event_bus_service.event_bus_listener import WebhookEventListener  # Listener for direct dispatch
from marvin.services.event_bus_service.event_bus_service import EventBusService  # Event bus for dispatching
from marvin.services.event_bus_service.event_types import (  # Core event system types
    INTERNAL_INTEGRATION_ID,  # Default integration ID for internal events
    Event,
    EventBusMessage,
    # EventDocumentType, # EventDocumentType was imported but not used directly here
    EventOperation,
    EventTypes,
    EventWebhookData,
)

logger = get_logger(__name__)


def _get_state_file_path() -> Path:
    """Get path to scheduler state file in data directory."""
    return get_app_dirs().DATA_DIR / "scheduler_state.json"


def _load_last_ran() -> datetime:
    """Load last_ran timestamp from state file, or current time if missing."""
    state_file = _get_state_file_path()
    if not state_file.exists():
        return datetime.now(UTC)

    try:
        with open(state_file) as f:
            state = json.load(f)
        return datetime.fromisoformat(state["last_ran"])
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger = get_logger()
        logger.warning(f"Failed to load scheduler state: {e}. Using current time.")
        return datetime.now(UTC)


def _save_last_ran(timestamp: datetime) -> None:
    """Save last_ran timestamp to state file atomically."""
    state_file = _get_state_file_path()
    state = {"last_ran": timestamp.isoformat(), "updated_at": datetime.now(UTC).isoformat()}

    # Ensure directory exists
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write via temp file
    temp_file = state_file.with_suffix(".tmp")
    with open(temp_file, "w") as f:
        json.dump(state, f, indent=2)
    temp_file.replace(state_file)


def post_group_webhooks(start_dt: datetime | None = None, group_id: UUID4 | None = None) -> None:  # Renamed group_id to group_id_filter
    """
    Posts webhook_task events to the event bus for a specific group or all groups.

    This function determines a time window (from `start_dt` or the persisted `last_ran`
    timestamp to the current UTC time) and dispatches a `webhook_task` event
    for each relevant group. The `WebhookEventListener` will then pick up this
    event and process webhooks scheduled within that time window for the group.

    Args:
        start_dt (datetime | None, optional): The start datetime of the window for
            finding scheduled webhooks. If None, uses the persisted `last_ran`
            timestamp from the state file. Defaults to None.
        group_id_filter (UUID4 | None, optional): If provided, only processes webhooks
            for this specific group ID. If None, processes for all groups.
            Defaults to None.
    """
    # Determine the start of the time window for webhook processing.
    # If `start_dt` is not provided, load the last_ran timestamp from the state file.
    # This ensures that overlapping runs or missed schedules can be accounted for.
    effective_start_dt = start_dt or _load_last_ran()

    # The end of the time window is the current UTC time.
    current_run_time = datetime.now(UTC)

    target_group_ids: list[UUID4]
    if group_id is None:
        # If no specific group_id is provided, fetch all group IDs to process.
        with session_context() as session:  # Create a new DB session context
            repos = get_repositories(session, group_id=None)  # Use non-scoped repos to get all groups
            all_groups_page = repos.groups.page_all(PaginationQuery(page=1, per_page=-1))  # Fetch all groups
            target_group_ids = [group.id for group in all_groups_page.items]
    else:
        # If a specific group_id is provided, process only that group.
        target_group_ids = [group_id]

    # Dispatch a webhook_task event for each target group.
    for current_group_id in target_group_ids:
        event_type = EventTypes.webhook_task  # The type of event to dispatch

        # Prepare the document data for the event, specifying the time window.
        # The `document_type` for EventWebhookData is typically set by the listener if needed,
        # or could be set to a generic type here. The commented-out line suggests it might
        # have been intended to be set based on individual webhook configs, which is complex here.
        event_document = EventWebhookData(
            # document_type= relevant_webhook.webhook_type, # This would require fetching webhooks here
            operation=EventOperation.info,  # Indicates this is an informational/trigger event
            webhook_start_dt=effective_start_dt,  # Start of the processing window
            webhook_end_dt=current_run_time,  # End of the processing window
        )

        # Get an instance of the event bus service (can be created on-the-fly if no state needed beyond bg_tasks)
        event_bus = EventBusService()  # Assuming default constructor is fine for synchronous dispatch if no bg_tasks
        event_bus.dispatch(
            integration_id=INTERNAL_INTEGRATION_ID,  # Identifies this as an internal Marvin task
            group_id=current_group_id,  # The specific group this event is for
            event_type=event_type,
            document_data=event_document,
            message=f"Scheduled webhook processing for group {current_group_id}",  # Descriptive message
        )

    # Persist the current run time after successful dispatch to all groups
    _save_last_ran(current_run_time)


def post_single_webhook(webhook_config: WebhookRead, message: str = "Test Webhook Event", user_id=None) -> None:
    """
    Triggers a single, specific webhook, typically for testing purposes.

    This function bypasses the main event bus dispatch for group-wide tasks and
    directly uses the `WebhookEventListener` to publish an event targeting only
    the provided webhook configuration. The time window for the event data is
    set to a minimal range around the epoch, effectively meaning "now" or "any time"
    for a test, as the listener will match this specific webhook instance.

    Args:
        webhook_config (WebhookRead): The Pydantic schema of the webhook to be triggered.
                                      Must contain `group_id` and `url`.
        message (str, optional): A message to include in the test event.
                                 Defaults to "Test Webhook Event".
    """
    # Use a minimal datetime range (epoch) for the test event's window,
    # as we are targeting a specific webhook, not a schedule.
    epoch_time = datetime.min.replace(tzinfo=UTC)
    event_type = EventTypes.webhook_task  # Standard event type for webhook execution

    # Prepare the document data for the event.
    # The `document_type` might be set based on `webhook_config.webhook_type` if needed by the listener/publisher.
    event_document = EventWebhookData(
        # document_type=webhook_config.webhook_type, # Set based on the specific webhook being tested
        operation=EventOperation.info,  # Test is an informational operation
        webhook_start_dt=epoch_time,  # Minimal start time
        webhook_end_dt=epoch_time,  # Minimal end time
    )

    # Construct the event object
    test_event = Event(
        message=EventBusMessage.from_type(event_type, body=message),
        event_type=event_type,
        integration_id=f"marvin_test_single_webhook_{webhook_config.id}",
        document_data=event_document,
        workspace_id=webhook_config.group_id,
        user_id=user_id,
    )

    # Initialize a WebhookEventListener for the group of the specified webhook
    listener = WebhookEventListener(webhook_config.group_id)
    # Directly publish to this single webhook configuration
    # The `publish_to_subscribers` method of WebhookEventListener expects a list of WebhookRead objects.
    listener.publish_to_subscribers(test_event, [webhook_config])
