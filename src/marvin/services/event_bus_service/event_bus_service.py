"""
This module defines the `EventBusService` for handling event dispatching
within the Marvin application.

The service allows different parts of the application to publish events,
and it ensures these events are routed to appropriate listeners (like
webhook, integration or email listeners) for further processing, such as sending
notifications. Events can be dispatched synchronously or as background tasks.

The `EventSource` class is also defined here, potentially for structuring
event metadata, though it's not directly used by `EventBusService` in this file.
"""

from typing import Any  # For EventSource.kwargs and EventSource.dict() return

from fastapi import BackgroundTasks, Depends  # For background tasks and dependency injection
from pydantic import UUID4  # For UUID type hinting
from sqlalchemy.orm.session import Session  # SQLAlchemy session type

# Marvin core and utility imports
from marvin.db.db_setup import generate_session  # generate_session is used in as_dependency
from marvin.services import BaseService  # Base service class for common functionality

# Event listener implementations
from marvin.services.event_bus_service.event_bus_listener import (
    AuditLogListener,
    AutomationReactionListener,
    ConsoleEventListener,
    EmailEventListener,
    EventListenerBase,
    IndexingReactionListener,
    IntegrationEventListener,
    MediaEmbedReactionListener,
    PlatformAlertListener,
    ScheduledTaskListener,
    SiteRebuildReactionListener,
    SmartCollectionReactionListener,
    WebhookEventListener,
    WorkspaceAlertListener,
)
from marvin.services.events.event_catalog import INTERNAL_EVENT_TYPES  # scheduler plumbing, logged quietly

# Core event types used by the bus
from .event_types import Event, EventBusMessage, EventDocumentDataBase, EventTypeBase

# settings = get_app_settings() # Instance not used directly in this file
# ALGORITHM = "HS256" # Constant not used in this file


class EventSource:
    """
    A data class for representing the source or context of an event.

    This class can be used to encapsulate details about what triggered an event,
    such as the type of event, the type of item related to the event, and the
    specific item's ID, along with any other relevant keyword arguments.

    Note: This class is defined here but not directly instantiated or used by
    `EventBusService` within this file. It might be intended for use by
    event producers before they call `EventBusService.dispatch`.
    """

    event_type: str
    """A string identifying the type of event (e.g., "item_created", "user_login")."""
    item_type: str
    """A string identifying the type of item related to the event (e.g., "user_profile")."""
    item_id: UUID4 | int  # Assuming item_id can also be an integer
    """The unique identifier of the item related to the event."""
    kwargs: dict[str, Any]
    """A dictionary for any additional context-specific data related to the event source."""

    def __init__(self, event_type: str, item_type: str, item_id: UUID4 | int, **kwargs: Any) -> None:
        """
        Initializes an EventSource instance.

        Args:
            event_type (str): The type of event.
            item_type (str): The type of item related to the event.
            item_id (UUID4 | int): The ID of the item.
            **kwargs (Any): Additional keyword arguments to store as context.
        """
        self.event_type = event_type
        self.item_type = item_type
        self.item_id = item_id
        self.kwargs = kwargs

    def dict(self) -> dict[str, Any]:
        """
        Returns a dictionary representation of the EventSource instance.
        The `item_id` is converted to a string.
        """
        return {
            "event_type": self.event_type,
            "item_type": self.item_type,
            "item_id": str(self.item_id),  # Ensure item_id is string for consistent serialization
            **self.kwargs,
        }


class EventBusService(BaseService):
    """
    Service for dispatching events to registered listeners.

    This service takes an event, constructs a standardized `Event` object,
    and then publishes it to relevant listeners (e.g., Webhooks, Integrations, Email).
    It can operate synchronously or dispatch event publishing as a background task
    if a `BackgroundTasks` instance is provided.
    """

    bg_tasks: BackgroundTasks | None = None  # Corrected attribute name from `bg` to `bg_tasks`
    """Optional FastAPI BackgroundTasks instance for asynchronous event publishing."""
    session: Session | None = None  # This session is primarily for the `as_dependency` factory method.
    """Optional SQLAlchemy session, mainly used when service is instantiated as a dependency."""

    def __init__(
        self,
        bg_tasks: BackgroundTasks | None = None,  # Renamed `bg` to `bg_tasks`
        session: Session | None = None,  # Session passed here is often from `as_dependency`
    ) -> None:
        """
        Initializes the EventBusService.

        Args:
            bg_tasks (BackgroundTasks | None, optional): A FastAPI `BackgroundTasks`
                instance. If provided, event publishing will be added as a background task.
                Defaults to None (synchronous publishing).
            session (Session | None, optional): A SQLAlchemy session. This is primarily
                for convenience when the service is used as a FastAPI dependency that
                itself requires a session, though the core event dispatch logic here
                doesn't directly use this session instance itself (listeners manage their own).
                Defaults to None.
        """
        self.bg_tasks = bg_tasks
        self.session = session  # Stored, but not directly used by dispatch logic here.

    def _get_listeners(self, group_id: UUID4) -> list[EventListenerBase]:
        """
        Retrieves a list of initialized event listeners for a given group ID.

        The order of listeners determines the order in which they might process events.
        AuditLogListener MUST be first to ensure events are persisted even if other listeners fail.
        Current order: AuditLog (persistence), reactions, Console (debug), Webhook, Integration, Email.

        Args:
            group_id (UUID4): The ID of the group for which to get listeners.
                              Listeners are often group-specific.

        Returns:
            list[EventListenerBase]: A list of event listener instances.
        """
        # The order of listeners can be significant if one listener's action
        # depends on another or if there's a desired notification priority.
        # AuditLogListener is first to ensure all events are persisted to the database
        # even if subsequent listeners (webhooks, notifications) fail.
        # ScheduledTaskListener must run before webhooks to execute tasks that may trigger webhooks.
        return [
            AuditLogListener(group_id),  # Persists all events to event_log table (MUST BE FIRST).
            ScheduledTaskListener(group_id),  # Executes scheduled tasks when triggered.
            IndexingReactionListener(group_id),  # Keeps the RAG index fresh for every registered indexable type.
            MediaEmbedReactionListener(group_id),  # Warms the media-embed cache before a rebuild reads it.
            SiteRebuildReactionListener(group_id),  # Queues a (coalesced) site rebuild when published content changes.
            AutomationReactionListener(group_id),  # Flavor B: runs user-configured automations on trigger events.
            SmartCollectionReactionListener(group_id),  # Materializes smart-collection membership on entry changes.
            ConsoleEventListener(group_id),  # Logs all events to console for debugging.
            WebhookEventListener(group_id),  # Handles custom webhook integrations for the group.
            IntegrationEventListener(group_id),  # Runs integration actions wired to events.
            EmailEventListener(group_id),  # Fires email templates on matching events.
            PlatformAlertListener(group_id),  # Sends platform alerts past the bell (Admin → Platform alerts).
            WorkspaceAlertListener(group_id),  # Sends the workspace's failures past the bell (Automation → Notifications).
        ]

    def _publish_event(self, event: Event, group_id: UUID4) -> None:
        """
        Publishes a given event to all relevant listeners for the specified group.

        This method iterates through the listeners obtained from `_get_listeners`.
        For each listener, it retrieves the specific subscribers for the event and
        then instructs the listener to publish the event to those subscribers.

        Args:
            event (Event): The `Event` object to publish.
            group_id (UUID4): The ID of the group associated with this event.
        """
        # Internal comments from original code:
        # "my event tipe is webhook_task > Should I use the webhook listener or just webhook_task"
        # -> The current logic iterates all listeners. Each listener's `get_subscribers` method
        #    will determine if it's interested in the event type.
        # "are we sure we want to use the webhook listener first?"
        # -> The order is defined in `_get_listeners`. If specific order is crucial, it's managed there.

        for listener in self._get_listeners(group_id):
            try:
                subscribers = listener.get_subscribers(event)
                if subscribers:  # If the listener has relevant subscribers for this event
                    listener.publish_to_subscribers(event, subscribers)
            except Exception as e:
                # Log error during listener processing but continue with other listeners.
                self.logger.error(
                    f"Error processing listener {type(listener).__name__} for event {event.event_type.name} in group {group_id}: {e}",
                    exc_info=True,
                )

    def dispatch(
        self,
        integration_id: str,  # Identifier for the system/module dispatching the event
        group_id: UUID4,  # Group context for the event
        event_type: EventTypeBase,  # The type of event (enum member)
        document_data: EventDocumentDataBase | None,  # Data associated with the event
        message: str = "",  # Optional human-readable message for the event
        user_id: UUID4 | None = None,  # User who triggered the event
        entity_id: UUID4 | None = None,  # Primary entity the event is about
        entity_type: str | None = None,  # Type of the primary entity
        reaction_depth: int = 0,  # Automation/reaction hop count (loop-guard); 0 for user/system actions
        correlation_id: str | None = None,  # Causal-chain id; inherits the ambient scope when omitted
    ) -> None:
        """
        Dispatches an event to the event bus.

        Constructs an `Event` object and then publishes it either as a background
        task (if `bg_tasks` is available) or synchronously.

        Args:
            integration_id (str): An identifier for the source or integration
                                  that is dispatching the event (e.g., "registration", "task_scheduler").
            group_id (UUID4): The ID of the group this event pertains to.
            event_type (EventTypeBase): The type of the event being dispatched.
            document_data (EventDocumentDataBase | None): The Pydantic model containing
                data relevant to the event. Can be None if the event carries no specific data.
            message (str, optional): A descriptive message accompanying the event.
                                     Defaults to "".
            user_id (UUID4 | None, optional): The ID of the user who triggered this event.
                                              None for system-triggered events. Defaults to None.
            entity_id (UUID4 | None, optional): The ID of the primary entity this event is about
                                                (e.g., entry_id, asset_id). Defaults to None.
            entity_type (str | None, optional): The type of the primary entity
                                                (e.g., "entry", "asset"). Defaults to None.
        """
        # Resolve the causal-chain id: an explicit arg wins, else inherit the ambient correlation
        # scope (a reaction cascade / an EntryService emit batch), else mint one (a fresh root). Read
        # synchronously here so it's baked into the Event even if publishing is deferred.
        from marvin.services.event_bus_service.correlation import current_correlation_id, new_correlation_id

        resolved_correlation_id = correlation_id or current_correlation_id.get() or new_correlation_id()

        # Construct the full Event object
        event_payload = Event(
            message=EventBusMessage.from_type(event_type, body=message),  # Standardized message structure
            event_type=event_type,
            integration_id=integration_id,
            document_data=document_data,  # The actual data payload of the event
            workspace_id=group_id,
            user_id=user_id,
            entity_id=entity_id,
            entity_type=entity_type,
            reaction_depth=reaction_depth,
            correlation_id=resolved_correlation_id,
        )

        event_name = event_type.name if hasattr(event_type, "name") else str(event_type)
        is_internal = event_name in INTERNAL_EVENT_TYPES  # scheduler plumbing: logged at debug level

        if self.bg_tasks:
            if not is_internal:
                self.logger.info(f"EVENT DISPATCHED: {event_name} [{integration_id}]")
            else:
                self.logger.debug(f"EVENT DISPATCHED: {event_name} [{integration_id}]")
            self.bg_tasks.add_task(self._publish_event, event=event_payload, group_id=group_id)
        else:
            if not is_internal:
                self.logger.info(f"EVENT DISPATCHED: {event_name} [{integration_id}]")
            else:
                self.logger.debug(f"EVENT DISPATCHED: {event_name} [{integration_id}]")
            self._publish_event(event=event_payload, group_id=group_id)

    @classmethod
    def as_dependency(
        cls,
        bg_tasks: BackgroundTasks,  # FastAPI BackgroundTasks dependency
        session: Session = Depends(generate_session),  # FastAPI DB session dependency
    ):  # Return type is an instance of the class itself
        """
        Class method to provide an instance of `EventBusService` as a FastAPI dependency.

        This allows FastAPI to inject an `EventBusService` instance (configured with
        `BackgroundTasks` and a `Session`) into route handlers.

        Args:
            bg_tasks (BackgroundTasks): Injected by FastAPI.
            session (Session): Injected by FastAPI via `generate_session`.

        Returns:
            EventBusService: An instance of `EventBusService`.
        """
        return cls(bg_tasks=bg_tasks, session=session)
