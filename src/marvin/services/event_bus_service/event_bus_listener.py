"""
This module defines the base class and concrete implementations for event listeners
within the Marvin application's event bus system.

Event listeners are responsible for:
1. Identifying relevant subscribers (e.g., Apprise URLs, webhook configurations)
   for a given event.
2. Publishing the event data to these subscribers using an appropriate publisher
   (e.g., `ApprisePublisher`, `WebhookPublisher`).

The module includes:
- `EventListenerBase`: An abstract base class defining the event listener interface
  and providing context managers for resource management (DB sessions, repositories).
- `AppriseEventListener`: A listener that finds Apprise URLs subscribed to an event
  and publishes event data to them, potentially enriching URLs with event parameters.
- `WebhookEventListener`: A listener that finds scheduled webhooks relevant to an event
  (specifically `webhook_task` events), potentially processes data based on webhook
  type, and publishes to the webhook URLs.
"""

import contextlib  # For contextmanager decorator
import json  # For serializing event data
from abc import ABC, abstractmethod  # For abstract base classes
from collections.abc import Generator  # For generator type hints
from datetime import UTC, datetime  # For datetime operations
from logging import Logger
from typing import Any, cast  # For type casting
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit  # For URL manipulation

from fastapi.encoders import jsonable_encoder  # For encoding Pydantic models to JSON-compatible dicts
from pydantic import UUID4  # For UUID type hinting
from sqlalchemy import select  # For SQLAlchemy select statements

# from sqlalchemy import func # `func` was imported but not used
from sqlalchemy.orm.session import Session  # SQLAlchemy session type

# Marvin specific imports
from marvin.core.root_logger import get_logger  # Application logger
from marvin.db.db_setup import session_context  # Context manager for DB sessions
from marvin.db.models.groups.webhooks import GroupWebhooksModel  # , Method # Method enum not directly used here
from marvin.repos.repository_factory import AllRepositories  # Central repository access
from marvin.schemas.group.event import GroupEventNotifierPrivate  # Schema for private notifier details
from marvin.schemas.group.webhook import WebhookRead  # Schema for reading webhook configurations
from marvin.services.webhooks.all_webhooks import AllWebhooks, get_webhooks  # For accessing webhook runners

from .event_types import (  # Core event system types
    Event,
    EventNameSpace,
    EventOperation,
    EventTypes,
    EventWebhookData,
)
from .publisher import ApprisePublisher, PublisherLike, WebhookPublisher  # Publisher implementations


class EventListenerBase(ABC):
    """
    Abstract base class for event listeners.

    Provides a common structure for event listeners, including initialization
    with a group ID and a publisher, and abstract methods for retrieving
    subscribers and publishing to them. It also includes context managers
    for ensuring database sessions and repository access.
    """

    _logger: Logger | None = None

    _session: Session | None = None
    """Optional pre-existing SQLAlchemy session."""
    _repos: AllRepositories | None = None
    """Optional pre-existing AllRepositories instance."""
    _webhooks: AllWebhooks | None = None  # Added for WebhookEventListener consistency
    """Optional pre-existing AllWebhooks instance."""

    def __init__(self, group_id: UUID4, publisher: PublisherLike) -> None:
        """
        Initializes the EventListenerBase.

        Args:
            group_id (UUID4): The ID of the group this listener is associated with.
                              Events processed may be scoped to this group.
            publisher (PublisherLike): An instance of a publisher (e.g., ApprisePublisher)
                                       used to send out notifications.
        """
        self.group_id: UUID4 = group_id
        """The group ID this listener is primarily concerned with."""
        self.publisher: PublisherLike = publisher
        """The publisher instance used to dispatch events."""
        # Initialize private attributes for lazy loading of resources
        self._session = None
        self._repos = None
        self._webhooks = None  # Initialize webhooks attribute

    @property
    def logger(self) -> Logger:
        """
        Provides access to the Marvin application logger.

        Initializes the logger on first access.
        """
        if not self._logger:
            self._logger = get_logger("event_bus_listener")
        return self._logger

    @abstractmethod
    def get_subscribers(self, event: Event) -> list[Any]:  # Return type can vary by implementation
        """
        Abstract method to get a list of all subscribers for a given event.

        Subclasses must implement this to determine who should receive the event
        (e.g., list of Apprise URLs, list of WebhookRead objects).

        Args:
            event (Event): The event for which to find subscribers.

        Returns:
            list[Any]: A list of subscribers. The type of items in the list
                       depends on the concrete listener implementation.
        """
        ...

    @abstractmethod
    def publish_to_subscribers(self, event: Event, subscribers: list[Any]) -> None:  # Param type matches get_subscribers
        """
        Abstract method to publish the given event to all provided subscribers.

        Subclasses must implement this to define how the event is dispatched
        using `self.publisher`.

        Args:
            event (Event): The event to publish.
            subscribers (list[Any]): A list of subscribers (format depends on listener)
                                     to which the event should be published.
        """
        ...

    @contextlib.contextmanager
    def ensure_session(self) -> Generator[Session, None, None]:
        """
        Ensures a SQLAlchemy session is available within a context.

        If `self._session` was provided during construction (e.g., within an existing
        request-response cycle), that session is yielded. Otherwise, a new session
        is created using `session_context` for the duration of the context, and
        it's automatically closed upon exiting.

        This is crucial for listeners that might operate both within a web request
        (session provided) and in background tasks (session needs to be created).

        Yields:
            Generator[Session, None, None]: The active SQLAlchemy session.
        """
        if self._session is None:
            # If no session exists, create one using the session_context manager
            with session_context() as new_session:
                self._session = new_session  # Store for potential reuse within this listener instance
                yield self._session
                self._session = None  # Clear after use if it was temporary
        else:
            # If a session already exists, yield it directly
            yield self._session

    @contextlib.contextmanager
    def ensure_repos(self, group_id: UUID4) -> Generator[AllRepositories, None, None]:
        """
        Ensures an `AllRepositories` instance is available within a context.

        Uses `ensure_session` to get a database session and then provides an
        `AllRepositories` instance initialized with that session and the given `group_id`.
        If `self._repos` was pre-configured, it's used directly.

        Args:
            group_id (UUID4): The group ID to scope the repositories to.

        Yields:
            Generator[AllRepositories, None, None]: The `AllRepositories` instance.
        """
        if self._repos is None:
            # If no repositories instance exists, create one within an ensured session context
            with self.ensure_session() as current_session:
                self._repos = AllRepositories(current_session, group_id=group_id)
                yield self._repos
                self._repos = None  # Clear after use if temporary
        else:
            # If a repositories instance already exists, yield it
            yield self._repos

    @contextlib.contextmanager
    def ensure_webhooks(self, group_id: UUID4) -> Generator[AllWebhooks, None, None]:
        """
        Ensures an `AllWebhooks` instance is available within a context.

        Uses `ensure_session` to get a database session and then provides an
        `AllWebhooks` instance initialized for the given `group_id`.
        If `self._webhooks` was pre-configured, it's used directly.

        Args:
            group_id (UUID4): The group ID for which to get webhook runners.

        Yields:
            Generator[AllWebhooks, None, None]: The `AllWebhooks` instance.
        """
        if self._webhooks is None:
            # If no webhooks instance exists, create one within an ensured session context
            with self.ensure_session() as current_session:
                self._webhooks = get_webhooks(current_session, group_id=group_id)
                yield self._webhooks
                self._webhooks = None  # Clear after use if temporary
        else:
            yield self._webhooks


class AppriseEventListener(EventListenerBase):
    """
    Event listener that publishes events to Apprise-compatible notification services.

    It retrieves configured Apprise URLs for a group that are subscribed to the
    specific event type. It can also update these URLs with event-specific data
    as query parameters for certain Apprise URL schemes (e.g., JSON, XML).
    """

    _option_value_field_name: str = "option"  # Field name on GroupEventNotifierOptionsSummary to get "namespace.slug"

    def __init__(self, group_id: UUID4) -> None:
        """
        Initializes the AppriseEventListener for a specific group.

        Args:
            group_id (UUID4): The ID of the group whose Apprise notifiers will be used.
        """
        super().__init__(group_id, ApprisePublisher())  # Uses ApprisePublisher for dispatching

    def get_subscribers(self, event: Event) -> list[GroupEventNotifierPrivate]:
        """
        Retrieves a list of enabled notifier objects subscribed to the given event.

        Returns the matching `GroupEventNotifierPrivate` objects so that
        `publish_to_subscribers` can fire and log per-notifier.
        """
        if event.event_type == EventTypes.webhook_task:
            return []

        target_option = f"{EventNameSpace.namespace.value}.{event.event_type.name.replace('-', '_')}"
        self.logger.debug(f"Target Event {target_option}")

        matching: list[GroupEventNotifierPrivate] = []
        with self.ensure_repos(self.group_id) as repos:
            enabled_notifiers: list[GroupEventNotifierPrivate] = repos.group_event_notifier.multi_query(
                {"enabled": True}, override_schema=GroupEventNotifierPrivate
            )
            for notifier in enabled_notifiers:
                if not notifier.apprise_url:
                    continue
                for option_summary in notifier.options:
                    if getattr(option_summary, self._option_value_field_name, None) == target_option:
                        matching.append(notifier)
                        break

        return matching

    def publish_to_subscribers(self, event: Event, subscribers: list[GroupEventNotifierPrivate]) -> None:
        """
        Publishes the event to each notifier individually, logging per-notifier.
        """
        from marvin.services.secrets.resolver import resolve

        for notifier in subscribers:
            resolved_url = resolve(notifier.apprise_url, group_id=self.group_id)
            enriched = self.update_urls_with_event_data([resolved_url], event)
            self.logger.info(f"Notifier '{notifier.name}' → {resolved_url}")
            self.publisher.publish(
                event,
                enriched,
                notifier_id=notifier.id,
                group_id=self.group_id,
                event_type=event.event_type.name,
            )

    @staticmethod
    def update_urls_with_event_data(apprise_urls: list[str], event: Event) -> list[str]:
        """
        Updates Apprise URLs with event-specific data as query parameters.

        For certain URL schemes (JSON, XML, FORM), it adds event details (like type, ID,
        timestamp, and document_data) as query parameters prefixed with ":". This allows
        Apprise to include this data in the notification payload for those services.

        Args:
            apprise_urls (list[str]): The list of raw Apprise URLs.
            event (Event): The event containing data to be added to URLs.

        Returns:
            list[str]: The list of Apprise URLs, potentially updated with event data.
        """
        # Prepare event data parameters for URL encoding
        event_params = {
            "event_type": event.event_type.name,
            "integration_id": event.integration_id,
            # Serialize document_data to a JSON string for URL parameter
            "document_data": json.dumps(jsonable_encoder(event.document_data)),
            "event_id": str(event.event_id),  # Convert UUID to string
            "timestamp": event.timestamp.isoformat() if event.timestamp else "",  # ISO format or empty string
        }
        # Filter out None values from params, as they shouldn't be in query string
        filtered_event_params = {k: v for k, v in event_params.items() if v is not None}

        processed_urls = []
        for url in apprise_urls:
            if AppriseEventListener.is_custom_data_url_scheme(url):  # Check if URL scheme supports custom data
                # Prepend ":" to keys for Apprise custom key-value pairs via query params
                apprise_custom_params = {f":{k}": v for k, v in filtered_event_params.items()}
                processed_urls.append(AppriseEventListener.merge_query_parameters(url, apprise_custom_params))
            else:
                processed_urls.append(url)  # URL scheme does not support custom data, use as is
        return processed_urls

    @staticmethod
    def merge_query_parameters(url_string: str, params_to_add: dict[str, str]) -> str:  # Renamed params
        """
        Merges additional query parameters into an existing URL string.

        Args:
            url_string (str): The original URL, which may or may not have existing query parameters.
            params_to_add (dict[str, str]): A dictionary of query parameters to add or update.

        Returns:
            str: The new URL string with merged query parameters.
        """
        scheme, netloc, path, query_string, fragment = urlsplit(url_string)
        existing_query_params = parse_qs(query_string)  # Parse existing query string into a dict

        # Update with new parameters. parse_qs values are lists, so ensure new params are also lists for consistency.
        for key, value in params_to_add.items():
            existing_query_params[key] = [value]  # Override or add as a list with one item

        new_query_string = urlencode(existing_query_params, doseq=True)  # Re-encode query parameters
        return urlunsplit((scheme, netloc, path, new_query_string, fragment))  # Reconstruct the URL

    @staticmethod
    def is_custom_data_url_scheme(url_string: str) -> bool:  # Renamed from is_custom_url
        """
        Checks if the given URL string uses a scheme that supports Apprise custom key-value data via query parameters.

        Args:
            url_string (str): The Apprise URL string.

        Returns:
            bool: True if the scheme is one of "form(s)", "json(s)", or "xml(s)"; False otherwise.
        """
        # Ensure URL is a string before splitting
        scheme = str(url_string).split(":", 1)[0].lower()
        # List of Apprise schemes that are known to support custom data via query parameters prefixed with ":"
        return scheme in ["form", "forms", "json", "jsons", "xml", "xmls"]


def _resolve_webhook_headers(webhook_config: "WebhookRead", group_id) -> dict[str, str] | None:
    """Resolve {{SLUG}} references in webhook headers using the configured secret backend."""
    raw = getattr(webhook_config, "headers", None) or getattr(webhook_config, "headers_json", None)
    if not raw:
        return None
    from marvin.services.secrets.resolver import resolve_dict

    return resolve_dict(raw, group_id)


class WebhookEventListener(EventListenerBase):
    """
    Event listener that handles events by triggering configured group webhooks.

    It specifically listens for `EventTypes.webhook_task` events, which are expected
    to carry `EventWebhookData` detailing a time range. It then finds scheduled
    webhooks within that time range for the group and publishes event data to them.
    It can also invoke registered functions based on `webhook.webhook_type` to generate
    dynamic data for the webhook payload.
    """

    def __init__(self, group_id: UUID4) -> None:
        """
        Initializes the WebhookEventListener for a specific group.

        Args:
            group_id (UUID4): The ID of the group whose webhooks will be processed.
        """
        super().__init__(group_id, WebhookPublisher())  # Uses WebhookPublisher for dispatching

    def get_subscribers(self, event: Event) -> list[WebhookRead]:
        """
        Retrieves a list of webhooks that should receive this event.

        This method handles two types of webhook triggers:
        1. Scheduled webhooks (`EventTypes.webhook_task`) - time-based triggers
        2. Event-subscribed webhooks - webhooks that subscribe to specific event types

        Args:
            event (Event): The event to find subscribers for.

        Returns:
            list[WebhookRead]: A list of `WebhookRead` schemas for webhooks that
                               should be triggered by this event.
        """
        if event.event_type == EventTypes.webhook_task and isinstance(event.document_data, EventWebhookData):
            webhook_event_data: EventWebhookData = cast(EventWebhookData, event.document_data)
            scheduled = self.get_scheduled_webhooks(webhook_event_data.webhook_start_dt, webhook_event_data.webhook_end_dt)
            self.logger.debug(f"webhook_task: {len(scheduled)} scheduled webhook(s) in window")
            return scheduled

        # Event-driven: find webhooks subscribed to this event type
        with self.ensure_session() as session:
            db_webhooks = (
                session.execute(
                    select(GroupWebhooksModel).where(
                        GroupWebhooksModel.enabled == True,  # noqa: E712
                        GroupWebhooksModel.group_id == self.group_id,
                    )
                )
                .scalars()
                .all()
            )

            filtered = [
                wh
                for wh in db_webhooks
                if wh.subscribed_events
                and event.event_type.name in wh.subscribed_events
                and getattr(wh.webhook_type, "value", None) == "event_driven"
            ]

            if filtered:
                self.logger.info(
                    f"event:{event.event_type.name} → {len(filtered)} webhook(s): " + ", ".join(wh.name or str(wh.id) for wh in filtered)
                )
            else:
                self.logger.debug(f"event:{event.event_type.name} → no webhook subscribers")

            return [WebhookRead.model_validate(wh) for wh in filtered]

    def publish_to_subscribers(self, event: Event, subscribers_webhooks: list[WebhookRead]) -> None:
        """Publish event data to each webhook subscriber."""
        from marvin.services.webhooks.substitution import apply_substitutions

        if event.event_type != EventTypes.webhook_task:
            # Event-driven path
            for webhook_config in subscribers_webhooks:
                self.logger.debug(f"  → firing event-driven webhook '{webhook_config.name}' [{webhook_config.method.name} {webhook_config.url}]")
                resolved_headers = _resolve_webhook_headers(webhook_config, self.group_id)
                payload_override = None
                if webhook_config.custom_payload:
                    ws_name, ws_slug = "", ""
                    try:
                        with self.ensure_repos(self.group_id) as repos:
                            grp = repos.groups.get_one(self.group_id)
                            if grp:
                                ws_name = getattr(grp, "name", "") or ""
                                ws_slug = getattr(grp, "slug", "") or ""
                    except Exception:
                        pass
                    ctx = {
                        "trigger": event.event_type.name,
                        "timestamp": event.timestamp.isoformat() if event.timestamp else "",
                        "workspace_name": ws_name,
                        "workspace_slug": ws_slug,
                    }
                    base = jsonable_encoder(event, exclude_none=True)
                    if "eventType" in base and hasattr(event.event_type, "name"):
                        base["eventType"] = event.event_type.name
                    base["meta"] = apply_substitutions(webhook_config.custom_payload, self.group_id, ctx)
                    payload_override = base
                self.publisher.publish(
                    event,
                    [webhook_config.url],
                    method=webhook_config.method.name,
                    webhook_id=webhook_config.id,
                    group_id=self.group_id,
                    headers=resolved_headers,
                    payload_override=payload_override,
                )
            return

        # Scheduled webhook_task path
        if not isinstance(event.document_data, EventWebhookData):
            self.logger.warning(f"WebhookEventListener: unexpected document_data type: {type(event.document_data)}")
            return

        webhook_event_data: EventWebhookData = cast(EventWebhookData, event.document_data)
        now_iso = datetime.now(UTC).isoformat()

        # Build substitution context once — used by all webhooks in this batch
        workspace_name = ""
        workspace_slug = ""
        try:
            with self.ensure_repos(self.group_id) as repos:
                group = repos.groups.get_one(self.group_id)
                if group:
                    workspace_name = getattr(group, "name", "") or ""
                    workspace_slug = getattr(group, "slug", "") or ""
        except Exception:
            pass

        context = {
            "timestamp": now_iso,
            "workspace_name": workspace_name,
            "workspace_slug": workspace_slug,
            "trigger": "scheduled",
        }

        for webhook_config in subscribers_webhooks:
            self.logger.debug(
                f"  → scheduled webhook '{webhook_config.name}' "
                f"[{webhook_config.method.name if webhook_config.method else 'POST'} {webhook_config.url}] "
                f"type={webhook_config.webhook_type.value if webhook_config.webhook_type else 'generic'}"
            )

            handler_data: dict = {}
            webhook_type_name = webhook_config.webhook_type.value if webhook_config.webhook_type else "generic"

            if webhook_event_data.operation == EventOperation.info:
                with self.ensure_webhooks(self.group_id) as webhook_runners:
                    handler = webhook_runners.get_webhook_handler(webhook_type_name)
                    if handler:
                        try:
                            handler_data = handler.info(webhook_config, context)
                        except Exception as e:
                            self.logger.error(f"Error calling .info() for webhook {webhook_config.name} (type={webhook_type_name}): {e}")

            # Mirror event-driven shape: context at top level, stats in data
            clean_payload: dict = {
                "timestamp": now_iso,
                "workspaceId": str(self.group_id),
                "workspaceName": workspace_name,
                "workspaceSlug": workspace_slug,
                "webhookType": webhook_type_name,
            }
            if handler_data:
                clean_payload["documentData"] = handler_data
            if webhook_config.custom_payload:
                clean_payload["meta"] = apply_substitutions(webhook_config.custom_payload, self.group_id, context)

            self.logger.info(
                f"WEBHOOK FIRING: '{webhook_config.name}' "
                f"[{webhook_config.method.name if webhook_config.method else 'POST'} {webhook_config.url}] "
                f"type={webhook_type_name}"
            )
            resolved_headers = _resolve_webhook_headers(webhook_config, self.group_id)
            self.publisher.publish(
                event,
                [webhook_config.url],
                method=webhook_config.method.name,
                webhook_id=webhook_config.id,
                group_id=self.group_id,
                headers=resolved_headers,
                payload_override=clean_payload,
            )

    def get_scheduled_webhooks(self, start_datetime: datetime, end_datetime: datetime) -> list[WebhookRead]:  # Renamed params
        """
        Fetches all enabled webhooks for the listener's group that are scheduled
        to run within the specified datetime window (inclusive of start, exclusive of end).

        The comparison is done on the `scheduled_time` field of the webhooks,
        compared against the full datetime values (converted to UTC).

        Args:
            start_datetime (datetime): The start of the datetime window (inclusive).
            end_datetime (datetime): The end of the datetime window (exclusive).

        Returns:
            list[WebhookRead]: A list of `WebhookRead` schemas for matching scheduled webhooks.
        """
        with self.ensure_session() as session:
            # Convert start/end datetimes to UTC for comparison with stored datetime values
            # Build the query for fetching scheduled webhooks

            stmt = select(GroupWebhooksModel).where(
                GroupWebhooksModel.enabled == True,  # noqa: E712 - SQLAlchemy specific comparison
                GroupWebhooksModel.scheduled_time >= start_datetime.astimezone(UTC),  # Compare full datetime (inclusive)
                GroupWebhooksModel.scheduled_time < end_datetime.astimezone(UTC),  # Compare full datetime (exclusive end)
                GroupWebhooksModel.group_id == self.group_id,  # Scope to listener's group
            )
            # Execute query and convert SQLAlchemy models to Pydantic schemas
            db_webhooks = session.execute(stmt).scalars().all()
            return [WebhookRead.model_validate(db_webhook) for db_webhook in db_webhooks]


class ScheduledTaskListener(EventListenerBase):
    """
    Event listener that executes scheduled tasks when triggered.

    This listener responds to scheduled_task.triggered events by:
    1. Looking up the appropriate handler via TaskHandlerRegistry
    2. Executing the handler with the task configuration
    3. Logging execution results
    4. Emitting completion/failure events
    5. Updating task execution state
    """

    def __init__(self, group_id: UUID4) -> None:
        """
        Initializes the ScheduledTaskListener for a specific group.

        Args:
            group_id (UUID4): The ID of the group this listener is associated with.
        """
        from .publisher import ConsolePublisher  # We don't actually publish anything, but need a publisher

        super().__init__(group_id, ConsolePublisher())

    def get_subscribers(self, event: Event) -> list[str]:
        """
        Returns a list indicating this listener should handle the event.

        Only subscribes to scheduled_task.triggered events.

        Args:
            event (Event): The event to check.

        Returns:
            list[str]: Returns ["scheduled_task_handler"] if this is a triggered event, else empty list.
        """
        if event.event_type == EventTypes.scheduled_task_triggered:
            return ["scheduled_task_handler"]
        return []

    def publish_to_subscribers(self, event: Event, subscribers: list[str]) -> None:
        """
        Executes the scheduled task.

        Args:
            event (Event): The triggered event containing task data.
            subscribers (list[str]): List of subscribers (always ["scheduled_task_handler"]).
        """
        import traceback

        from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
        from marvin.services.scheduled_tasks import TaskHandlerRegistry

        # Extract task data from event
        if not event.document_data:
            self.logger.error("ScheduledTaskListener: No document_data in event")
            return

        task_id = getattr(event.document_data, "task_id", None)
        if not task_id:
            self.logger.error("ScheduledTaskListener: No task_id in document_data")
            return

        # Load the task from database
        with self.ensure_repos(self.group_id) as repos:
            task = repos.session.get(ScheduledTaskModel, task_id)
            if not task:
                self.logger.error(f"ScheduledTaskListener: Task {task_id} not found")
                return

            start_time = datetime.now(UTC)

            # Import event bus for handler to use
            from marvin.services.event_bus_service.event_bus_service import EventBusService

            event_bus = EventBusService(bg_tasks=None)

            try:
                # Emit started event
                event_bus.dispatch(
                    integration_id="scheduled_tasks",
                    group_id=task.group_id,
                    event_type=EventTypes.scheduled_task_started,
                    document_data=event.document_data,  # Reuse same task data
                    message=f"Scheduled task '{task.name}' execution started",
                )

                # Get and execute handler
                handler = TaskHandlerRegistry.get_handler(task.task_type)
                self.logger.info(f"Executing scheduled task: {task.name} (type: {task.task_type})")
                output = handler.execute(task, event_bus)

                # Calculate duration
                end_time = datetime.now(UTC)
                duration_ms = int((end_time - start_time).total_seconds() * 1000)

                # Log the run — unless a handler said there was nothing to report and nobody was
                # watching. A frequent task (every 2 minutes is 720 runs a day) otherwise buries its
                # own real events under identical "nothing happened" rows. Liveness is not lost:
                # last_run_at/last_status below are updated either way. A run someone triggered by
                # hand always logs, because they asked and deserve an answer.
                by_hand = event.integration_id != "scheduled_tasks"
                if output is not None or by_hand:
                    repos.scheduled_task_executions.log_execution(
                        task_id=task.id,
                        group_id=task.group_id,
                        status="success",
                        executed_at=start_time,
                        duration_ms=duration_ms,
                        output=output if output is not None else "Nothing to do.",
                    )

                # Update task state
                repos.scheduled_tasks.update_execution_state(
                    task_id=task.id,
                    last_run_at=start_time,
                    last_status="success",
                    last_duration_ms=duration_ms,
                    failure_count=0,  # Reset on success
                )

                # Recalculate next_run_at for recurring tasks
                next_run = repos.scheduled_tasks._compute_next_run(task.schedule_type, task.schedule_config)
                if next_run:
                    repos.scheduled_tasks.update_next_run(task.id, next_run)
                elif task.schedule_type == "once":
                    # One-time task — clear next_run_at so scheduler won't re-fire it
                    repos.scheduled_tasks.update_next_run(task.id, None)

                # Emit completed event
                event_bus.dispatch(
                    integration_id="scheduled_tasks",
                    group_id=task.group_id,
                    event_type=EventTypes.scheduled_task_completed,
                    document_data=event.document_data,
                    message=f"Scheduled task '{task.name}' completed successfully in {duration_ms}ms",
                )

                self.logger.info(f"Scheduled task '{task.name}' completed successfully in {duration_ms}ms")

            except ValueError as e:
                # Handler not found
                self.logger.error(f"Scheduled task handler error: {e}")
                self._handle_task_failure(repos, task, start_time, str(e), None, event_bus, event)

            except Exception as e:
                # Handler execution failed
                error_msg = str(e)
                error_trace = traceback.format_exc()
                self.logger.error(f"Scheduled task '{task.name}' failed: {error_msg}\n{error_trace}")
                self._handle_task_failure(repos, task, start_time, error_msg, error_trace, event_bus, event)

    def _handle_task_failure(
        self,
        repos,
        task,
        start_time,
        error_message: str,
        error_traceback: str | None,
        event_bus,
        event: Event,
    ) -> None:
        """Helper to handle task execution failures."""
        end_time = datetime.now(UTC)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # Log failed execution
        repos.scheduled_task_executions.log_execution(
            task_id=task.id,
            group_id=task.group_id,
            status="failed",
            executed_at=start_time,
            duration_ms=duration_ms,
            error_message=error_message,
            error_traceback=error_traceback,
        )

        # Update task state with incremented failure count
        repos.scheduled_tasks.update_execution_state(
            task_id=task.id,
            last_run_at=start_time,
            last_status="failed",
            last_duration_ms=duration_ms,
            failure_count=task.failure_count + 1,
        )

        # Still recalculate next_run_at so the task keeps retrying on schedule
        next_run = repos.scheduled_tasks._compute_next_run(task.schedule_type, task.schedule_config)
        if next_run:
            repos.scheduled_tasks.update_next_run(task.id, next_run)

        # Emit failed event
        event_bus.dispatch(
            integration_id="scheduled_tasks",
            group_id=task.group_id,
            event_type=EventTypes.scheduled_task_failed,
            document_data=event.document_data,
            message=f"Scheduled task '{task.name}' failed: {error_message}",
        )


class IndexingReactionListener(EventListenerBase):
    """
    Reaction listener that keeps the RAG index fresh for every registered indexable type.

    Driven entirely by the indexable-type registry (``embeddings_registry``): it reacts to each
    type's index/delete events, (re)embeds on index events (gated per-type via ``should_index``),
    and purges embeddings on delete events. Adding a new indexable type needs NO change here — just
    a ``register_indexable(...)``.

    Deliberately:
      - best-effort: any failure is logged and swallowed, so it can never break a write;
      - a no-op when the workspace has AI disabled or a provider without embeddings;
      - acyclic: it only emits ai_embeddings_reindexed, which re-triggers nothing here.
    """

    def __init__(self, group_id: UUID4) -> None:
        from .publisher import ConsolePublisher  # We act on the event; we don't publish through it.

        super().__init__(group_id, ConsolePublisher())

    def get_subscribers(self, event: Event) -> list[str]:
        """Act only on events some indexable type cares about; cheap check, no DB access."""
        from marvin.services.ai.embeddings_registry import trigger_events

        return ["ai_index"] if event.event_type in trigger_events() else []

    def publish_to_subscribers(self, event: Event, subscribers: list[str]) -> None:
        from marvin.services.ai.embeddings_registry import delete_descriptor_for, index_descriptor_for

        del_desc = delete_descriptor_for(event.event_type)
        idx_desc = index_descriptor_for(event.event_type)
        desc = idx_desc or del_desc
        if desc is None:
            return
        entity_id = getattr(event.document_data, desc.id_field, None) or event.entity_id
        if not entity_id:
            self.logger.error(f"IndexingReactionListener: {event.event_type} carried no {desc.id_field}")
            return

        from marvin.services.ai.embeddings import default_embedding_model, index_entity, purge_embeddings

        # Delete → purge the entity's embeddings; no provider needed.
        if del_desc is not None:
            with self.ensure_session() as session:
                n = purge_embeddings(session, self.group_id, del_desc.entity_type, entity_id)
            self.logger.info(f"Purged {n} embedding chunk(s) for deleted {del_desc.entity_type} {entity_id}")
            return

        # Index → (re)embed, gated by the type's should_index.
        # del_desc handled and returned above; `desc = idx_desc or del_desc` was non-None, so idx_desc holds here.
        assert idx_desc is not None
        from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider

        with self.ensure_session() as session:
            # Resolve the workspace provider; quietly no-op when AI is off or unavailable.
            try:
                provider = get_workspace_ai_provider(session, self.group_id)
            except AIDisabledError:
                return
            except Exception as e:
                self.logger.warning(f"IndexingReactionListener: provider unavailable: {e}")
                return
            if not getattr(provider, "supports_embeddings", False):
                return
            model = default_embedding_model(provider.provider_type)
            if not model:
                return

            obj = session.get(idx_desc.model, entity_id)
            if not obj or obj.group_id != self.group_id:
                self.logger.warning(f"IndexingReactionListener: {idx_desc.entity_type} {entity_id} not found for this workspace")
                return
            has_index = self._has_index(session, idx_desc.entity_type, entity_id, model)
            if not idx_desc.should_index(obj, event.event_type, has_index):
                return
            # Content gate: a too-thin object (e.g. a bare icon/logo asset) doesn't belong in the
            # semantic index. Skip it — and purge any stale embedding if it just lost its content.
            if not idx_desc.content_ok(obj):
                if has_index:
                    from marvin.services.ai.embeddings import purge_embeddings

                    purge_embeddings(session, self.group_id, idx_desc.entity_type, entity_id, model)
                    session.commit()
                return

            try:
                chunks = index_entity(session, self.group_id, idx_desc.entity_type, obj.id, idx_desc.text(obj), provider, model)
            except Exception as e:
                self.logger.warning(f"IndexingReactionListener: embed failed for {idx_desc.entity_type} {entity_id}: {e}")
                return

        verb = "on " + event.event_type.name.split("_", 1)[-1]  # e.g. "on published", "on updated"
        self.logger.info(f"Auto-indexed {idx_desc.entity_type} {entity_id} ({chunks} chunk(s)) {verb}")
        self._emit_reindexed(model, chunks, idx_desc.entity_type, verb)

    def _has_index(self, session: Session, entity_type: str, entity_id: UUID4, model: str) -> bool:
        """True if this entity already has embedding chunks for the given model."""
        from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

        return (
            session.query(AIEmbeddingModel).filter_by(group_id=self.group_id, entity_type=entity_type, entity_id=entity_id, model_id=model).first()
            is not None
        )

    def _emit_reindexed(self, model: str, chunks: int, entity_type: str = "entry", verb: str = "on publish") -> None:
        """Surface the auto-index as an ai_embeddings_reindexed event (audit log + notifications)."""
        from marvin.services.event_bus_service.event_bus_service import EventBusService

        from .event_types import EventAIEmbeddingsData

        try:
            workspace_name = None
            with self.ensure_repos(self.group_id) as repos:
                grp = repos.groups.get_one(self.group_id)
                workspace_name = getattr(grp, "name", None) if grp else None
            EventBusService(bg_tasks=None).dispatch(
                integration_id="ai_operations",
                group_id=self.group_id,
                event_type=EventTypes.ai_embeddings_reindexed,
                document_data=EventAIEmbeddingsData(
                    model_id=model,
                    entities_indexed=1,
                    chunks_indexed=chunks,
                    workspace_id=self.group_id,
                    workspace_name=workspace_name,
                ),
                message=f"Auto-indexed 1 {entity_type} ({chunks} chunks) {verb}",
            )
        except Exception as e:
            self.logger.error(f"IndexingReactionListener: failed to emit reindexed event: {e}")


class SmartCollectionReactionListener(EventListenerBase):
    """
    Reaction listener that keeps smart-collection membership in sync.

    When an entry's type or status changes (created / updated / published / unpublished /
    archived / restored), re-evaluate which of the workspace's smart collections it belongs to
    and add or remove EntryCollections rows accordingly. The read path (renderers-core,
    publishing) is unchanged — it reads junction rows exactly as for a manually-curated
    collection. Declarative rules, imperative materialization, unchanged reads.

    entry_deleted is intentionally omitted: EntryCollections has ON DELETE CASCADE, so the DB
    removes membership automatically. Best-effort — any failure is logged and swallowed, so it
    can never break entry writes.
    """

    _TRIGGERS = (
        EventTypes.entry_created,
        EventTypes.entry_updated,
        EventTypes.entry_published,
        EventTypes.entry_unpublished,
        EventTypes.entry_archived,
        EventTypes.entry_restored,
    )

    def __init__(self, group_id: UUID4) -> None:
        from .publisher import ConsolePublisher  # We act on the event; we don't publish through it.

        super().__init__(group_id, ConsolePublisher())

    def get_subscribers(self, event: Event) -> list[str]:
        """Act only on entry lifecycle events; cheap check, no DB access."""
        return ["smart_collections"] if event.event_type in self._TRIGGERS else []

    def publish_to_subscribers(self, event: Event, subscribers: list[str]) -> None:
        entry_id = getattr(event.document_data, "entry_id", None) or event.entity_id
        if not entry_id:
            return

        from marvin.db.models.platform.entries import Entries
        from marvin.services.collections.smart_collections import sync_entry

        with self.ensure_session() as session:
            entry = session.get(Entries, entry_id)
            if not entry or entry.group_id != self.group_id:
                return
            try:
                changed = sync_entry(session, self.group_id, entry)
                if changed:
                    session.commit()
                    self.logger.info(f"Smart collections: synced entry {entry_id} ({changed} membership change(s))")
            except Exception as e:
                session.rollback()
                self.logger.warning(f"SmartCollectionReactionListener: sync failed for entry {entry_id}: {e}")


class AutomationReactionListener(EventListenerBase):
    """Flavor B: run the workspace's *user-configured* automations for a triggering event.

    Where the reaction listeners above are hardcoded (Flavor A — developer-defined), this one loads
    data-defined automations (`WorkspaceAutomationModel`) and runs their `event → conditions →
    actions` pipelines via the automation engine. Best-effort: any failure is logged and swallowed,
    so an automation can never break event dispatch.

    Loop-guard: an automation's `emit_event`/write-back re-dispatches at `reaction_depth + 1`; we
    refuse to react once depth reaches `MAX_REACTION_DEPTH`, so data-defined chains stay finite.
    """

    # Automation lifecycle events drive the chained / on-error trigger types (not the event dropdown).
    _AUTOMATION_EVENT_NAMES = ("automation_ran", "automation_failed")

    def __init__(self, group_id: UUID4) -> None:
        from .publisher import ConsolePublisher  # We act on the event; we don't publish through it.

        super().__init__(group_id, ConsolePublisher())

    def get_subscribers(self, event: Event) -> list[str]:
        from marvin.services.automation.engine import MAX_REACTION_DEPTH
        from marvin.services.automation.triggers import TRIGGER_EVENT_NAMES_SET

        if getattr(event, "reaction_depth", 0) >= MAX_REACTION_DEPTH:
            return []  # loop-guard: a chain has gone deep enough — stop reacting
        name = event.event_type.name
        if name in TRIGGER_EVENT_NAMES_SET or name == "incoming_webhook" or name in self._AUTOMATION_EVENT_NAMES:
            return ["automation"]
        return []

    def publish_to_subscribers(self, event: Event, subscribers: list[str]) -> None:
        from fastapi.encoders import jsonable_encoder

        dd = event.document_data
        # Flatten the event's document_data into the match context so `$event.<field>` works for ANY
        # event family (asset_type, resource_type, form_name, …) — not just entries. snake_case field
        # names (model_dump default) match how conditions are written. The curated explicit keys below
        # override, so they can't be shadowed by a document_data field of the same name.
        dd_fields: dict = {}
        if dd is not None:
            try:
                dd_fields = jsonable_encoder(dd, by_alias=False)
            except Exception:
                dd_fields = {}

        entry_id = getattr(dd, "entry_id", None) or event.entity_id
        automation_id = getattr(dd, "automation_id", None)
        event_ctx = {
            **dd_fields,
            "event_type": event.event_type.name,
            "entry_id": entry_id,
            "automation_id": str(automation_id) if automation_id else None,
            "automation_slug": getattr(dd, "automation_slug", None),
            # Incoming-webhook triggers key on the webhook slug; conditions/actions reach the request
            # body via $event.payload.*
            "webhook_slug": getattr(dd, "webhook_slug", None),
            "payload": getattr(dd, "payload", None),
            # What an update changed — lets conditions key on transitions, e.g.
            # $event.after.status == "review" (only-changed-fields, so this reads as "changed to").
            "changed_fields": getattr(dd, "changed_fields", None) or [],
            "before": getattr(dd, "before", None) or {},
            "after": getattr(dd, "after", None) or {},
            "user_id": event.user_id,
            "reaction_depth": getattr(event, "reaction_depth", 0),
            # Thread the triggering event's chain id so the whole reaction cascade shares it.
            "correlation_id": getattr(event, "correlation_id", None),
        }
        from marvin.services.automation.engine import run_automations_for_event
        from marvin.services.automation.recorder import ExecutionRecorder

        with self.ensure_session() as session:
            try:
                ran = run_automations_for_event(
                    session,
                    self.group_id,
                    event_ctx,
                    logger=self.logger,
                    recorder=ExecutionRecorder(session, self.group_id),
                )
            except Exception as e:
                session.rollback()
                self.logger.warning(f"AutomationReactionListener: engine error: {e}")
                return
        if ran:
            self.logger.info(f"Ran {ran} automation(s) for {event.event_type.name}")


class ConsoleEventListener(EventListenerBase):
    """
    Event listener that logs all events to the console for debugging.

    This listener is useful during development to see events in real-time
    without needing to configure external webhooks or notification services.
    """

    def __init__(self, group_id: UUID4) -> None:
        """
        Initializes the ConsoleEventListener for a specific group.

        Args:
            group_id (UUID4): The ID of the group this listener is associated with.
        """
        from .publisher import ConsolePublisher

        super().__init__(group_id, ConsolePublisher())

    def get_subscribers(self, event: Event) -> list[str]:
        """
        Returns a list of subscribers for console logging.

        For ConsoleEventListener, we always return ["console"] to indicate
        that all events should be logged to the console.

        Args:
            event (Event): The event to log.

        Returns:
            list[str]: Always returns ["console"] to log all events.
        """
        _INTERNAL = {
            EventTypes.webhook_task,
            EventTypes.scheduled_task_triggered,
            EventTypes.scheduled_task_started,
            EventTypes.scheduled_task_completed,
            EventTypes.scheduled_task_failed,
        }
        if event.event_type in _INTERNAL:
            return []
        return ["console"]

    def publish_to_subscribers(self, event: Event, subscribers: list[str]) -> None:
        """
        Publishes the event to the console logger.

        Args:
            event (Event): The event to log.
            subscribers (list[str]): List of subscribers (ignored, always logs to console).
        """
        # Use the ConsolePublisher to log the event
        self.publisher.publish(event, subscribers)


class EmailEventListener(EventListenerBase):
    """
    Event listener that fires email templates when a matching event occurs.

    Reads EmailEventSubscription rows for the group, resolves recipients,
    and sends email via EmailService._send_db_template.  When no workspace
    subscription exists for an event that has a system template mapping, a
    VirtualEmailSubscription pointing to the system template is used instead.
    """

    def __init__(self, group_id) -> None:
        from .publisher import ConsolePublisher

        super().__init__(group_id, ConsolePublisher())

    def get_subscribers(self, event: Event) -> list[Any]:
        from marvin.db.models.groups.email_templates import EmailTemplateModel
        from marvin.services.email.system_email_events import (
            SYSTEM_TEMPLATE_EVENT_MAP,
            VirtualEmailSubscription,
            get_template_type_for_event,
        )

        if event.event_type == EventTypes.webhook_task:
            return []

        with self.ensure_repos(self.group_id) as repos:
            workspace_subs = repos.email_event_subscriptions.multi_query({"event_type": event.event_type.name, "enabled": True})

            # Check for system template mapping for this event
            system_template_type = get_template_type_for_event(event.event_type.name)
            if not system_template_type:
                return workspace_subs

            system_mapping = SYSTEM_TEMPLATE_EVENT_MAP[system_template_type]

            # Find workspace templates of this type
            ws_templates_of_type = (
                repos.session.query(EmailTemplateModel)
                .filter(
                    EmailTemplateModel.template_type == system_template_type,
                    EmailTemplateModel.group_id == self.group_id,
                    EmailTemplateModel.enabled == True,  # noqa: E712
                )
                .all()
            )
            ws_template_ids = {t.id for t in ws_templates_of_type}

            # Find subscriptions that explicitly connect a workspace template of this type
            connected_subs = [sub for sub in workspace_subs if sub.template_id in ws_template_ids]

            if connected_subs:
                # Explicit connection via Events page — use only those
                self.logger.info(f"EmailEventListener: {len(connected_subs)} explicitly connected workspace template(s) for '{system_template_type}'")
                return connected_subs

            # No explicit connection — fall through to system template
            system_template = (
                repos.session.query(EmailTemplateModel)
                .filter(
                    EmailTemplateModel.group_id.is_(None),
                    EmailTemplateModel.template_type == system_template_type,
                )
                .first()
            )

            if system_template and system_template.enabled:
                return [
                    VirtualEmailSubscription(
                        template_id=system_template.id,
                        event_type=event.event_type.name,
                        recipient_type=system_mapping["recipient_type"],
                        recipient_field=system_mapping.get("recipient_field"),
                        recipient_email=system_mapping.get("recipient_email"),
                    )
                ]

            return workspace_subs

    def publish_to_subscribers(self, event: Event, subscribers: list[Any]) -> None:
        from marvin.db.models.groups.email_templates import EmailTemplateModel
        from marvin.services.email.email_service import EmailService
        from marvin.services.events.event_variables import build_event_variables, enrich_variables

        variables = enrich_variables(build_event_variables(event), self.group_id)
        email_service = EmailService(group_id=str(self.group_id))

        with self.ensure_session() as session:
            for sub in subscribers:
                template = session.get(EmailTemplateModel, sub.template_id)
                if template is None or not template.enabled:
                    self.logger.warning(f"EmailEventListener: template {sub.template_id} not found or disabled")
                    continue

                recipients = self._resolve_recipients(sub, variables, session)
                if not recipients:
                    self.logger.info(f"EmailEventListener: no recipients for subscription {sub.id} (event={event.event_type.name})")
                    continue

                for addr in recipients:
                    try:
                        self.logger.info(f"EmailEventListener: sending template '{template.name}' to {addr} for event {event.event_type.name}")
                        email_service._send_db_template(addr, template, variables)
                    except Exception as exc:
                        self.logger.error(
                            f"EmailEventListener: failed sending to {addr} (template={template.name}, event={event.event_type.name}): {exc}"
                        )

    def _resolve_recipients(self, sub: Any, variables: dict, session) -> list[str]:
        from marvin.db.models.users import Users
        from marvin.db.models.users.roles import WorkspaceRole
        from marvin.db.models.users.workspace_members import WorkspaceMembers

        match sub.recipient_type:
            case "event_field":
                field = sub.recipient_field
                if field and field in variables:
                    addr = variables[field]
                    if isinstance(addr, str) and addr and "@" in addr:
                        return [addr]
                    self.logger.warning(
                        f"EmailEventListener: event_field '{field}' resolved to non-email value "
                        f"'{addr}' for subscription {sub.id} — possible misconfiguration, skipping"
                    )
                    return []
                return []
            case "specific":
                if not sub.recipient_email:
                    return []
                return [a.strip() for a in sub.recipient_email.split(",") if a.strip()]
            case "admins":
                stmt = (
                    select(Users.email)
                    .join(WorkspaceMembers, WorkspaceMembers.user_id == Users.id)
                    .where(
                        WorkspaceMembers.group_id == self.group_id,
                        WorkspaceMembers.workspace_role.in_([WorkspaceRole.OWNER, WorkspaceRole.ADMIN]),
                    )
                )
                rows = session.execute(stmt).scalars().all()
                return [r for r in rows if r]
            case _:
                return []


class AuditLogListener(EventListenerBase):
    """
    Event listener that persists all events to the database for audit trail.

    This listener creates an immutable record of every event that occurs in Marvin,
    enabling event history queries, entity timelines, and user activity tracking.
    It should be registered first in the listener chain to ensure events are
    persisted even if subsequent listeners fail.
    """

    def __init__(self, group_id: UUID4) -> None:
        """
        Initializes the AuditLogListener for a specific group.

        Args:
            group_id (UUID4): The ID of the group this listener is associated with.
        """
        from .publisher import AuditLogPublisher

        super().__init__(group_id, AuditLogPublisher())

    def get_subscribers(self, event: Event) -> list[str]:
        """
        Returns a list of subscribers for audit logging.

        For AuditLogListener, we always return ["database"] to indicate
        that all events should be persisted to the event_log table.

        Args:
            event (Event): The event to persist.

        Returns:
            list[str]: ["database"] to persist the event, or [] to skip persistence
                       for non-audited internal plumbing events (the "nolog" set).
        """
        # Audit policy is declared per-event in the catalog (its `audited` flag). Events with no
        # catalog entry default to audited (safe). Set audited=False on a CatalogEntry to keep it
        # out of the audit trail — toggleable per event, no code change here.
        from marvin.services.events.event_catalog import get_catalog_entry

        entry = get_catalog_entry(event.event_type.name)
        if entry is not None and not entry.audited:
            return []
        return ["database"]

    def publish_to_subscribers(self, event: Event, subscribers: list[str]) -> None:
        """
        Publishes the event to the audit log database.

        Args:
            event (Event): The event to persist.
            subscribers (list[str]): List of subscribers (ignored, always persists to database).
        """
        # Use the AuditLogPublisher to persist the event
        self.publisher.publish(event, subscribers)


class IntegrationEventListener(EventListenerBase):
    """Runs integration actions wired to events (the integration_event_subscriptions table).

    This is how integrations are *consumed*: connect an integration's action to an event type and
    it fires whenever that event happens — the same subscribe-to-an-event model webhooks, apprise,
    and email use. The provider runs directly (no publisher), so there's no channel indirection.
    """

    def __init__(self, group_id: UUID4) -> None:
        super().__init__(group_id, cast(Any, None))  # runs provider actions directly; no publisher

    def get_subscribers(self, event: Event) -> list[dict]:
        if event.event_type == EventTypes.webhook_task:
            return []

        from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
        from marvin.db.models.groups.integrations import IntegrationModel

        event_name = event.event_type.name
        subs: list[dict] = []
        with self.ensure_session() as session:
            rows = (
                session.query(IntegrationEventSubscriptionModel)
                .filter(
                    IntegrationEventSubscriptionModel.group_id == self.group_id,
                    IntegrationEventSubscriptionModel.event_type == event_name,
                    IntegrationEventSubscriptionModel.enabled.is_(True),
                )
                .all()
            )
            for row in rows:
                integ = session.get(IntegrationModel, row.integration_id)
                if not integ or not integ.enabled:
                    continue
                # Snapshot everything needed so publish_to_subscribers is session-independent.
                subs.append(
                    {
                        "name": integ.name,
                        "provider": integ.provider,
                        "config": integ.config or {},
                        "secret_ref": integ.secret_ref,
                        "action": row.action,
                        "args": row.args or {},
                    }
                )
        if subs:
            self.logger.debug(f"event:{event_name} → {len(subs)} integration action(s)")
        return subs

    def publish_to_subscribers(self, event: Event, subscribers: list[dict]) -> None:
        if not subscribers:
            return

        try:
            from marvin.services.integrations import IntegrationContext, build_http, get_provider
        except ImportError:
            return
        from marvin.services.secrets.resolver import resolve_secret

        ctx_data = self._event_context(event)
        for sub in subscribers:
            try:
                provider = get_provider(sub["provider"])
            except KeyError:
                self.logger.warning(f"integration provider '{sub['provider']}' not installed; skipping")
                continue
            secret = resolve_secret(sub["secret_ref"], self.group_id) if sub["secret_ref"] else None
            ctx = IntegrationContext(config=sub["config"], secret=secret, logger=self.logger, http=build_http())
            args = self._template(sub["args"], ctx_data)
            try:
                provider.run_action(sub["action"], args, ctx)
                self.logger.info(f"integration '{sub['name']}' ran '{sub['action']}' on {event.event_type.name}")
            except Exception as e:  # noqa: BLE001 — one action failing must not affect the others
                self.logger.warning(f"integration '{sub['name']}' action '{sub['action']}' failed: {e}")

    def _event_context(self, event: Event) -> dict:
        """Flatten the event into a dict of {{placeholder}} values for action args."""
        data: dict = {}
        try:
            if event.document_data is not None:
                encoded = jsonable_encoder(event.document_data)
                if isinstance(encoded, dict):
                    data.update(encoded)
        except Exception:  # noqa: BLE001 — templating context is best-effort
            pass
        data.setdefault("event_type", event.event_type.name)
        if getattr(event, "entity_id", None) is not None:
            data.setdefault("entity_id", str(event.entity_id))
        if getattr(event, "entity_type", None) is not None:
            data.setdefault("entity_type", event.entity_type)
        if getattr(event, "message", None):
            data.setdefault("message", event.message)
        return data

    @staticmethod
    def _template(args: dict, ctx: dict):
        """Substitute {{field}} placeholders in string args with event-context values."""
        import re

        def render(value):
            if isinstance(value, str):
                return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(ctx.get(m.group(1), m.group(0))), value)
            if isinstance(value, dict):
                return {k: render(v) for k, v in value.items()}
            if isinstance(value, list):
                return [render(v) for v in value]
            return value

        return {k: render(v) for k, v in (args or {}).items()}
