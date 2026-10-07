"""
This module defines the base class and concrete implementations for event listeners
within the Marvin application's event bus system.

Event listeners are responsible for:
1. Identifying relevant subscribers (e.g., webhook configurations) for a given event.
2. Publishing the event data to these subscribers using an appropriate publisher
   (e.g., `WebhookPublisher`).

The module includes:
- `EventListenerBase`: An abstract base class defining the event listener interface
  and providing context managers for resource management (DB sessions, repositories).
- `WebhookEventListener`: A listener that finds scheduled webhooks relevant to an event
  (specifically `webhook_task` events), potentially processes data based on webhook
  type, and publishes to the webhook URLs.
"""

import contextlib  # For contextmanager decorator
from abc import ABC, abstractmethod  # For abstract base classes
from collections.abc import Generator  # For generator type hints
from datetime import UTC, datetime  # For datetime operations
from logging import Logger
from typing import Any, ClassVar, cast  # For type casting

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
from marvin.schemas.group.webhook import WebhookRead  # Schema for reading webhook configurations
from marvin.services.publish_visibility import is_publishable_type  # What the publishing API serves
from marvin.services.webhooks.all_webhooks import AllWebhooks, get_webhooks  # For accessing webhook runners

from .event_types import (  # Core event system types
    Event,
    EventOperation,
    EventTypes,
    EventWebhookData,
    WebhookMode,
    event_entity,
)
from .publisher import PublisherLike, WebhookPublisher  # Publisher implementations


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
            publisher (PublisherLike): An instance of a publisher (e.g., WebhookPublisher)
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
        (e.g., a list of WebhookRead objects).

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
        from marvin.db.models.groups.webhook_event_subscriptions import WebhookEventSubscriptionModel

        with self.ensure_session() as session:
            filtered = (
                session.execute(
                    select(GroupWebhooksModel)
                    .join(WebhookEventSubscriptionModel, WebhookEventSubscriptionModel.webhook_id == GroupWebhooksModel.id)
                    .where(
                        GroupWebhooksModel.enabled == True,  # noqa: E712
                        GroupWebhooksModel.group_id == self.group_id,
                        GroupWebhooksModel.webhook_type == WebhookMode.event_driven,
                        WebhookEventSubscriptionModel.event_type == event.event_type.name,
                    )
                )
                .scalars()
                .all()
            )

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
                    webhook_name=webhook_config.name,
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
                webhook_name=webhook_config.name,
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


class BuiltinReaction(EventListenerBase):
    """A reaction Marvin ships in code, as opposed to one a person wired up (workflows, webhooks, emails,
    integration actions). It says what it does (`label`) and which events it reacts to (`reacts_to()`), and
    `get_subscribers` matches on that same set — so what the Events hub lists can't drift from what runs.
    `builtin_reactions()` (end of this module) lists them."""

    label: ClassVar[str]
    """What it does, in a few words ("Queues a site rebuild")."""
    subscriber: ClassVar[str]
    """The subscriber name `get_subscribers` returns; the listener acts on the event itself."""
    REACTS_TO: ClassVar[frozenset[EventTypes]] = frozenset()

    @classmethod
    def reacts_to(cls) -> frozenset[EventTypes]:
        """The events it reacts to."""
        return cls.REACTS_TO

    def get_subscribers(self, event: Event) -> list[str]:
        """Act only on the events it reacts to; cheap check, no DB access."""
        return [self.subscriber] if event.event_type in self.reacts_to() else []


class ScheduledTaskListener(BuiltinReaction):
    """
    Event listener that executes scheduled tasks when triggered.

    This listener responds to scheduled_task.triggered events by:
    1. Looking up the appropriate handler via TaskHandlerRegistry
    2. Executing the handler with the task configuration
    3. Logging execution results
    4. Emitting completion/failure events
    5. Updating task execution state
    """

    label = "Runs the scheduled task"
    subscriber = "scheduled_task_handler"
    REACTS_TO = frozenset({EventTypes.scheduled_task_triggered})

    def __init__(self, group_id: UUID4) -> None:
        """
        Initializes the ScheduledTaskListener for a specific group.

        Args:
            group_id (UUID4): The ID of the group this listener is associated with.
        """
        from .publisher import ConsolePublisher  # We don't actually publish anything, but need a publisher

        super().__init__(group_id, ConsolePublisher())

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
                    entity_id=task.id,
                    entity_type="scheduled_task",
                )

                # Get and execute handler
                handler = TaskHandlerRegistry.get_handler(task.task_type)
                self.logger.info(f"Executing scheduled task: {task.name} (type: {task.task_type})")
                output = handler.execute(task, event_bus)

                # Calculate duration
                end_time = datetime.now(UTC)
                duration_ms = int((end_time - start_time).total_seconds() * 1000)

                # Log the run (execution row and scheduled_task_completed event) — unless a handler
                # said there was nothing to report and nobody was watching. A frequent task (every 2
                # minutes is 720 runs a day) otherwise buries its own real events under identical
                # "nothing happened" rows. Liveness is not lost: last_run_at/last_status below are
                # updated either way. A run someone triggered by hand always logs, because they asked
                # and deserve an answer; a failure always logs (_handle_task_failure).
                by_hand = event.integration_id != "scheduled_tasks"
                worth_recording = output is not None or by_hand
                if worth_recording:
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

                if worth_recording:
                    event_bus.dispatch(
                        integration_id="scheduled_tasks",
                        group_id=task.group_id,
                        event_type=EventTypes.scheduled_task_completed,
                        document_data=event.document_data,
                        message=f"Scheduled task '{task.name}' completed successfully in {duration_ms}ms",
                        entity_id=task.id,
                        entity_type="scheduled_task",
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
            entity_id=task.id,
            entity_type="scheduled_task",
        )


class IndexingReactionListener(BuiltinReaction):
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

    label = "Refreshes AI search"
    subscriber = "ai_index"

    @classmethod
    def reacts_to(cls) -> frozenset[EventTypes]:
        """Every registered indexable type's index and delete events."""
        from marvin.services.ai.embeddings_registry import trigger_events

        return frozenset(trigger_events())

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

            from marvin.services.ai.embeddings import chunks_unchanged, entity_chunks

            text = idx_desc.text(obj)
            # Most saves of a published item don't change what's indexed (a workflow writing metadata,
            # a status flag): skip the embedding call — and the event — when the chunks are identical.
            if chunks_unchanged(session, self.group_id, idx_desc.entity_type, obj.id, model, entity_chunks(text)):
                return
            try:
                chunks = index_entity(session, self.group_id, idx_desc.entity_type, obj.id, text, provider, model)
            except Exception as e:
                self.logger.warning(f"IndexingReactionListener: embed failed for {idx_desc.entity_type} {entity_id}: {e}")
                return

        verb = "on " + event.event_type.name.split("_", 1)[-1]  # e.g. "on published", "on updated"
        self.logger.info(f"Auto-indexed {idx_desc.entity_type} {entity_id} ({chunks} chunk(s)) {verb}")
        self._emit_reindexed(model, chunks, idx_desc.entity_type, verb, entity_id=obj.id)

    def _has_index(self, session: Session, entity_type: str, entity_id: UUID4, model: str) -> bool:
        """True if this entity already has embedding chunks for the given model."""
        from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel

        return (
            session.query(AIEmbeddingModel).filter_by(group_id=self.group_id, entity_type=entity_type, entity_id=entity_id, model_id=model).first()
            is not None
        )

    def _emit_reindexed(self, model: str, chunks: int, entity_type: str = "entry", verb: str = "on publish", entity_id: UUID4 | None = None) -> None:
        """Surface the auto-index as an ai_embeddings_reindexed event (audit log + notifications), about
        the one item it indexed."""
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
                entity_id=entity_id,
                entity_type=entity_type if entity_id else None,
            )
        except Exception as e:
            self.logger.error(f"IndexingReactionListener: failed to emit reindexed event: {e}")


class SmartCollectionReactionListener(BuiltinReaction):
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

    label = "Updates smart collections"
    subscriber = "smart_collections"
    REACTS_TO = frozenset(
        {
            EventTypes.entry_created,
            EventTypes.entry_updated,
            EventTypes.entry_published,
            EventTypes.entry_unpublished,
            EventTypes.entry_archived,
            EventTypes.entry_restored,
        }
    )

    def __init__(self, group_id: UUID4) -> None:
        from .publisher import ConsolePublisher  # We act on the event; we don't publish through it.

        super().__init__(group_id, ConsolePublisher())

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


class MediaEmbedReactionListener(BuiltinReaction):
    """
    Warms the platform-wide media-embed cache when an entry is saved, so the publishing API (which
    never calls a provider) has titles, thumbnails and players for the entry's media links by the time
    the site rebuilds. Runs before the site-rebuild listener for that reason.

    Best-effort: at most ``MAX_URLS`` links per save, only links without a fresh cache row, and any
    failure is logged and swallowed — it can never break a write. Emits nothing.
    """

    label = "Warms the media-embed cache"
    subscriber = "media_embeds"
    REACTS_TO = frozenset({EventTypes.entry_created, EventTypes.entry_updated, EventTypes.entry_published})
    MAX_URLS = 20

    def __init__(self, group_id: UUID4) -> None:
        from .publisher import ConsolePublisher  # We act on the event; we don't publish through it.

        super().__init__(group_id, ConsolePublisher())

    def publish_to_subscribers(self, event: Event, subscribers: list[str]) -> None:
        entry_id = getattr(event.document_data, "entry_id", None) or event.entity_id
        if not entry_id:
            return

        from marvin.db.models.platform.entries import Entries
        from marvin.db.models.platform.entry_types import EntryTypes
        from marvin.services.media_embeds.cache import warm
        from marvin.services.media_embeds.extract import entry_embed_urls

        with self.ensure_session() as session:
            entry = session.get(Entries, entry_id)
            if not entry or entry.group_id != self.group_id:
                return
            entry_type = session.get(EntryTypes, entry.entry_type_id) if entry.entry_type_id else None
            urls = entry_embed_urls(entry_type.schema_json if entry_type else None, entry.data_json)
            if not urls:
                return
            try:
                n = warm(session, urls, limit=self.MAX_URLS)
                if n:
                    self.logger.info(f"Media embeds: resolved {n} link(s) for entry {entry_id}")
            except Exception as e:
                session.rollback()
                self.logger.warning(f"MediaEmbedReactionListener: resolving links for entry {entry_id} failed: {e}")


class SiteRebuildReactionListener(BuiltinReaction):
    """
    Requests a static-site rebuild when published content changes, so a publish, an edit to a live
    entry, a collection change or a site-settings change reaches the site without a workflow.

    Requests are coalesced per workspace (services/site_rebuild): a burst of edits becomes one build,
    sent once they go quiet. Changes nothing a visitor can see are ignored: a draft saved or moved
    between workflow collections, anything done to an entry of a non-publishable type (a newsletter
    signup confirmed), and changes to a collection that isn't "Visible to sites" — unless that change
    is the visibility toggle itself. Visibility follows the publishing API (services/publish_visibility,
    `Collections.is_public`). Off when the workspace turns off "Rebuild the site automatically"
    (preferences.site_auto_rebuild). Best-effort: never breaks the write.
    """

    # Events that can change what a static site renders. Entry-scoped ones count only for a published
    # entry (or one leaving 'published') of a publishable type; an entry delete counts for any entry of
    # a publishable type (the row is gone, so its status is too). Collection events count only for a
    # public collection, or one changing visibility.
    ENTRY_EVENTS = frozenset(
        {
            EventTypes.entry_published,
            EventTypes.entry_unpublished,
            EventTypes.entry_archived,
            EventTypes.entry_updated,
            EventTypes.entry_added_to_collection,
            EventTypes.entry_removed_from_collection,
            EventTypes.entry_tag_attached,
            EventTypes.entry_tag_detached,
            EventTypes.entry_resource_attached,
            EventTypes.entry_resource_detached,
            EventTypes.asset_attached_to_entry,
            EventTypes.asset_detached_from_entry,
        }
    )
    ALWAYS_EVENTS = frozenset(
        {
            EventTypes.entry_deleted,
            EventTypes.collection_updated,
            EventTypes.collection_deleted,
            EventTypes.asset_updated,
            EventTypes.asset_deleted,
            EventTypes.resource_updated,
            EventTypes.resource_deleted,
            EventTypes.workspace_settings_changed,
        }
    )
    label = "Queues a site rebuild"
    subscriber = "site_rebuild"
    REACTS_TO = ENTRY_EVENTS | ALWAYS_EVENTS
    # Leaving 'published' is visible even though the entry no longer is.
    LEAVING_EVENTS = frozenset({EventTypes.entry_unpublished, EventTypes.entry_archived})
    COLLECTION_EVENTS = frozenset({EventTypes.collection_updated, EventTypes.collection_deleted})
    MEMBERSHIP_EVENTS = frozenset({EventTypes.entry_added_to_collection, EventTypes.entry_removed_from_collection})
    # Document-data fields that name the changed thing, for a change line whose message doesn't.
    TITLE_FIELDS = ("entry_title", "collection_name", "resource_name", "name")
    # EventBusMessage stores an empty body as the "generic" placeholder — not a description.
    EMPTY_BODY = "generic"
    # Workspace settings no site renders: a settings change touching only these queues no rebuild. A field
    # counts by its first dotted segment, so "agents" covers every "agents.<slug>[.<field>]" an agent edit names.
    UNSEEN_SETTINGS = frozenset({"audit_overrides", "agents"})

    def __init__(self, group_id: UUID4) -> None:
        from .publisher import ConsolePublisher

        super().__init__(group_id, ConsolePublisher())

    def publish_to_subscribers(self, event: Event, subscribers: list[str]) -> None:
        try:
            with self.ensure_session() as session:
                if not self._enabled(session):
                    return
                if not self._visible(session, event):
                    self.logger.debug(f"Site rebuild skipped: {event.event_type.name} changes nothing a site can see")
                    return
                from marvin.services.site_rebuild import request_rebuild

                request_rebuild(
                    session,
                    self.group_id,
                    f"content change: {event.message.body if event.message else event.event_type.name}"[:200],
                    change=self._change(event),
                )
        except Exception as e:
            self.logger.warning(f"SiteRebuildReactionListener: could not queue a rebuild: {e}")

    @classmethod
    def _change(cls, event: Event) -> dict:
        """The line this event adds to the rebuild's "what changed" list, worded like the event log."""
        from marvin.services.site_rebuild import rebuild_change

        message = getattr(event, "message", None)
        body = getattr(message, "body", None)
        label = body if body and body != cls.EMPTY_BODY else getattr(message, "title", None) or event.event_type.name.replace("_", " ").capitalize()
        names = (getattr(event.document_data, field, None) for field in cls.TITLE_FIELDS)
        title = next((n for n in names if isinstance(n, str) and n), None)
        if title and title not in label:
            label = f"{label} — {title}"
        entity_type, entity_id = event_entity(event)
        return rebuild_change(label, event.event_type.name, entity_type, entity_id)

    def _enabled(self, session: Session) -> bool:
        from marvin.db.models.groups.preferences import GroupPreferencesModel

        prefs = session.query(GroupPreferencesModel).filter_by(group_id=self.group_id).first()
        return getattr(prefs, "site_auto_rebuild", True) is not False

    def _visible(self, session: Session, event: Event) -> bool:
        """Whether this event changes what a site can see. When it can't tell, it says yes — a spare
        (coalesced) rebuild beats a stale site."""
        if event.event_type in self.COLLECTION_EVENTS:
            return self._collection_visible(session, event)
        if event.event_type == EventTypes.entry_deleted:
            return self._deleted_entry_visible(session, event)
        if event.event_type == EventTypes.workspace_settings_changed:
            changed = getattr(event.document_data, "changed_fields", None)
            return not changed or not {str(f).split(".", 1)[0] for f in changed} <= self.UNSEEN_SETTINGS
        if event.event_type in self.ALWAYS_EVENTS:
            return True
        return self._entry_visible(session, event)

    def _entry_visible(self, session: Session, event: Event) -> bool:
        entry_id = getattr(event.document_data, "entry_id", None) or event.entity_id
        if not entry_id:
            return True
        from marvin.db.models.platform.entries import Entries

        entry = session.get(Entries, entry_id)
        if entry is None:
            return True
        if entry.entry_type is not None and not is_publishable_type(entry.entry_type):
            return False  # never served, whatever its status
        if event.event_type in self.MEMBERSHIP_EVENTS and not self._collection_public(session, event.document_data):
            return False  # entries list only their public collections
        if event.event_type in self.LEAVING_EVENTS or entry.status == "published":
            return True
        # An update that took the entry out of 'published' (status in its changed fields) is visible too.
        before = getattr(event.document_data, "before", None) or {}
        return before.get("status") == "published"

    def _deleted_entry_visible(self, session: Session, event: Event) -> bool:
        """The row is gone; its type survives by slug in the event."""
        slug = getattr(event.document_data, "entry_type", None)
        if not slug:
            return True
        from marvin.db.models.platform import EntryTypes

        entry_type = session.query(EntryTypes).filter_by(group_id=self.group_id, slug=slug).first()
        return entry_type is None or is_publishable_type(entry_type)

    def _collection_visible(self, session: Session, event: Event) -> bool:
        data = event.document_data
        is_public = self._collection_public(session, data, getattr(data, "collection_id", None) or event.entity_id)
        was_public = (getattr(data, "before", None) or {}).get("is_public")
        return is_public or (was_public is not None and bool(was_public) != is_public)

    @staticmethod
    def _collection_public(session: Session, data, collection_id=None) -> bool:
        """The collection's visibility as the event recorded it, else as stored; unknown counts as public."""
        recorded = getattr(data, "is_public", None)
        if recorded is not None:
            return bool(recorded)
        collection_id = collection_id or getattr(data, "collection_id", None)
        if not collection_id:
            return True
        from marvin.db.models.platform import Collections

        collection = session.get(Collections, collection_id)
        return collection is None or bool(collection.is_public)


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
        from marvin.services.events.event_catalog import TRIGGERABLE_EVENT_TYPES

        if getattr(event, "reaction_depth", 0) >= MAX_REACTION_DEPTH:
            return []  # loop-guard: a chain has gone deep enough — stop reacting
        name = event.event_type.name
        if name in TRIGGERABLE_EVENT_TYPES or name == "incoming_webhook" or name in self._AUTOMATION_EVENT_NAMES:
            return ["automation"]
        return []

    def publish_to_subscribers(self, event: Event, subscribers: list[str]) -> None:
        from marvin.services.automation.context import event_context_from_event
        from marvin.services.automation.engine import run_automations_for_event
        from marvin.services.automation.recorder import ExecutionRecorder

        # The event's document_data flattened into `$event.*` (see automation.context) — the same
        # builder a workflow dry run replays a logged event through.
        event_ctx = event_context_from_event(event)
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
        from marvin.services.events.event_catalog import INTERNAL_EVENT_TYPES

        if event.event_type.name in INTERNAL_EVENT_TYPES:  # scheduler plumbing stays out of the console
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
            # A connection's "working again" notice also goes to every email route that delivered its alert.
            from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
            from marvin.services.integrations.errors import resolved_channel_rows

            delivered = resolved_channel_rows(repos.session, self.group_id, event, EmailEventSubscriptionModel, "email")
            if delivered:
                known = {sub.id for sub in workspace_subs}
                workspace_subs = [*workspace_subs, *(row for row in delivered if row.id not in known)]

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
                if template is not None and template.group_id is not None and str(template.group_id) != str(sub.group_id):
                    # Only this workspace's templates or system ones; never another workspace's.
                    template = None
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

        Args:
            event (Event): The event to persist.

        Returns:
            list[str]: ["database"] to persist the event, or [] when this workspace doesn't audit its type.
        """
        # The catalog declares each type's default (`audited`); a workspace admin may override it per type
        # (services/events/audit_settings.py). Locked (security) types and types without a catalog entry are
        # always audited, and so is everything if the workspace's setting can't be read.
        from marvin.services.events.audit_settings import is_audited

        if not is_audited(self.group_id, event.event_type.name):
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
    it fires whenever that event happens — the same subscribe-to-an-event model webhooks
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
            # A connection's "working again" notice also goes to every route that delivered its alert.
            from marvin.services.integrations.errors import resolved_channel_rows

            known = {row.id for row in rows}
            rows += [
                row
                for row in resolved_channel_rows(session, self.group_id, event, IntegrationEventSubscriptionModel, "integration")
                if row.id not in known
            ]
            for row in rows:
                integ = session.get(IntegrationModel, row.integration_id)
                if not integ or not integ.enabled:
                    continue
                # Snapshot everything needed so publish_to_subscribers is session-independent.
                subs.append(
                    {
                        "integration_id": integ.id,
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
        from marvin.services.integrations import errors
        from marvin.services.secrets.resolver import resolve_secret

        ctx_data = self._event_context(event)
        # Loop guard: delivering an integration alert never opens, bumps or resolves one — a broken
        # Slack connection must not alert about itself through itself.
        track = event.event_type.name not in errors.ALERT_EVENTS
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
                if track:  # connection scope: the provider's notify only — no entry to review, nothing to retry
                    errors.connection_failed(
                        self.group_id, sub.get("integration_id"), provider, sub["action"], e, source="subscription", secrets=(secret,)
                    )
                continue
            if track:
                errors.connection_succeeded(self.group_id, sub.get("integration_id"))

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


BUILTIN_REACTIONS: tuple[type[BuiltinReaction], ...] = (
    ScheduledTaskListener,
    IndexingReactionListener,
    MediaEmbedReactionListener,
    SiteRebuildReactionListener,
    SmartCollectionReactionListener,
)
"""Every built-in reaction, in the order EventBusService runs them."""


def builtin_reactions(event_type: EventTypes | str) -> list[tuple[str, type[BuiltinReaction]]]:
    """The built-in reactions to an event type (a member or its name), as (label, listener class) pairs."""
    name = getattr(event_type, "name", event_type)
    return [(cls.label, cls) for cls in BUILTIN_REACTIONS if name in {e.name for e in cls.reacts_to()}]
