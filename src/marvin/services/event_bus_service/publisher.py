"""
This module defines publisher implementations for the event bus system
within the Marvin application.

Publishers are responsible for taking a processed event and dispatching it
to external services or URLs. It includes:
- `PublisherLike`: A protocol defining the interface for publisher classes.
- `ApprisePublisher`: Publishes events to various notification services using the Apprise library.
- `WebhookPublisher`: Publishes events to specified URLs via HTTP requests (e.g., POST, GET).
"""

import time
from datetime import UTC, datetime
from typing import Any, Protocol  # For defining structural subtyping (interfaces)

import apprise  # Library for sending notifications to many services
import requests  # For making HTTP requests (used by WebhookPublisher)
from fastapi.encoders import jsonable_encoder  # For encoding Pydantic models to JSON

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.db.models._model_utils.guid import GUID
from marvin.db.models.groups.notification_execution_logs import NotificationExecutionLogModel
from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
from marvin.services.event_bus_service.event_types import Event, event_entity  # Core Event model

# from marvin.db.models.groups import Method # Method enum was imported but not used directly by string comparison in WebhookPublisher.
# If strict enum usage is desired, this import would be necessary.

# Default timeout for HTTP requests made by WebhookPublisher
DEFAULT_WEBHOOK_TIMEOUT = 15  # seconds

# Retry configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 2  # Exponential: 2^attempt seconds
RETRY_BACKOFF_MAX = 60  # Cap at 60 seconds


class PublisherLike(Protocol):
    """
    A protocol defining the interface for event publisher classes.

    Publishers are responsible for taking an `Event` object and a list of
    target notification URLs (or similar identifiers) and dispatching the
    event information to those targets.
    """

    def publish(self, event: Event, notification_urls: list[str], **kwargs) -> None:  # Added **kwargs for flexibility
        """
        Publishes an event to the specified notification URLs.

        Args:
            event (Event): The event object to publish.
            notification_urls (list[str]): A list of URLs or identifiers for the
                                           notification targets.
            **kwargs: Additional keyword arguments that specific publisher
                      implementations might require (e.g., HTTP method for webhooks).
        """
        ...  # Ellipsis indicates this is a protocol method to be implemented.


class ApprisePublisher:
    """
    Publishes events using the Apprise library to various notification services.
    """

    def __init__(self, hard_fail: bool = False) -> None:
        self.hard_fail: bool = hard_fail

    def publish(
        self,
        event: Event,
        notification_urls: list[str],
        notifier_id: GUID | None = None,
        group_id: GUID | None = None,
        event_type: str | None = None,
        **_: Any,
    ) -> None:
        if not notification_urls:
            return

        asset = apprise.AppriseAsset(async_mode=False, image_url_mask="")
        ap = apprise.Apprise(asset=asset)

        tags: list[str] = []
        for dest_url in notification_urls:
            tag = str(event.event_id)
            tags.append(tag)
            added = ap.add(dest_url, tag=tag)
            if not added and self.hard_fail:
                raise Exception(f"Apprise failed to add URL: {dest_url}")

        if not tags:
            return

        try:
            result = ap.notify(
                title=event.message.title,
                body=event.message.body,
                tag=list(set(tags)),
            )
            success = bool(result)
        except Exception as exc:
            _log_notification_execution(
                notifier_id=notifier_id,
                group_id=group_id,
                status="failed",
                event_type=event_type,
                error_message=str(exc),
                request_payload={"title": event.message.title, "body": event.message.body},
            )
            return

        _log_notification_execution(
            notifier_id=notifier_id,
            group_id=group_id,
            status="success" if success else "failed",
            event_type=event_type,
            request_payload={"title": event.message.title, "body": event.message.body},
        )


def _log_webhook_execution(
    webhook_id: GUID | None,
    group_id: GUID | None,
    status: str,  # 'success', 'failed', 'retrying'
    http_status_code: int | None = None,
    error_message: str | None = None,
    retry_attempt: int = 0,
    request_payload: dict | None = None,
    response_body: str | None = None,
) -> None:
    """Log webhook execution to database."""
    if webhook_id is None or group_id is None:
        return

    try:
        with session_context() as session:
            log = WebhookExecutionLogModel(
                session=session,
                webhook_id=webhook_id,
                group_id=group_id,
                executed_at=datetime.now(UTC),
                status=status,
                http_status_code=http_status_code,
                error_message=error_message,
                retry_attempt=retry_attempt,
                request_payload=request_payload,
                response_body=response_body,
            )
            session.add(log)
            session.commit()
    except Exception as e:
        logger = get_logger()
        logger.error(f"Failed to log webhook execution: {e}")


def _log_notification_execution(
    notifier_id: GUID | None,
    group_id: GUID | None,
    status: str,
    event_type: str | None = None,
    error_message: str | None = None,
    request_payload: dict | None = None,
) -> None:
    """Log Apprise notification execution to database."""
    if notifier_id is None or group_id is None:
        return

    try:
        with session_context() as session:
            log = NotificationExecutionLogModel(
                session=session,
                notifier_id=notifier_id,
                group_id=group_id,
                executed_at=datetime.now(UTC),
                status=status,
                event_type=event_type,
                error_message=error_message,
                request_payload=request_payload,
            )
            session.add(log)
            session.commit()
    except Exception as e:
        logger = get_logger()
        logger.error(f"Failed to log notification execution: {e}")


def _calculate_retry_delay(attempt: int) -> float:
    """Calculate exponential backoff: 2^attempt seconds, capped at 60."""
    return min(RETRY_BACKOFF_BASE**attempt, RETRY_BACKOFF_MAX)


class ConsolePublisher:
    """
    Publishes events to console/logs for debugging.

    This is a simple publisher that logs event information to the console,
    useful for development and debugging without needing external webhooks
    or notification services configured.
    """

    def __init__(self) -> None:
        """Initializes the ConsolePublisher."""
        self.logger = get_logger("event_console")

    def publish(self, event: Event, notification_urls: list[str], **_: Any) -> None:
        """
        Logs an event to the console.

        Args:
            event (Event): The event object to log.
            notification_urls (list[str]): Ignored for console publisher (always logs).
            **_ (Any): Catches any additional keyword arguments (ignored).
        """
        # Format the event nicely for console output
        separator = "=" * 80
        self.logger.info(separator)
        self.logger.info(f"🔔 EVENT DISPATCHED: {event.event_type.name}")
        self.logger.info(f"   Integration: {event.integration_id}")
        self.logger.info(f"   Message: {event.message.title}")
        if event.message.body and event.message.body != "generic":
            self.logger.info(f"   Body: {event.message.body}")
        if event.document_data:
            data_dict = jsonable_encoder(event.document_data)
            self.logger.info(f"   Document Type: {data_dict.get('documentType') or 'unknown'}")
            self.logger.info(f"   Operation: {data_dict.get('operation', 'unknown')}")
            for key, value in data_dict.items():
                if key not in ["documentType", "operation"]:
                    self.logger.info(f"   {key}: {value}")
        self.logger.info(separator)


class WebhookPublisher:
    """
    Publishes events to specified URLs via HTTP requests (webhooks).

    Supports different HTTP methods (GET, POST, PUT, DELETE). For methods that
    carry a body (POST, PUT), the event data is JSON-encoded and sent.
    Includes retry logic with exponential backoff and execution logging.
    """

    def __init__(self, hard_fail: bool = False) -> None:
        """
        Initializes the WebhookPublisher.

        Args:
            hard_fail (bool, optional): If True, an HTTPError will be raised if
                the webhook request returns a 4xx or 5xx status code.
                Defaults to False.
        """
        self.hard_fail: bool = hard_fail
        """If True, raise an exception on HTTP error status codes."""
        self.logger = get_logger()

    def publish(
        self,
        event: Event,
        notification_urls: list[str],
        method: str = "POST",
        webhook_id: GUID | None = None,
        group_id: GUID | None = None,
        headers: dict[str, str] | None = None,
        payload_override: dict | None = None,
        **_: Any,
    ) -> None:
        """
        Publishes event data to a list of notification URLs using the specified HTTP method.

        Includes retry logic with exponential backoff and logs execution attempts to the database.

        When ``payload_override`` is supplied it is sent instead of the serialized event object.
        POST and PUT requests use a body; GET and DELETE do not.

        Args:
            event (Event): The event object (used for metadata / fallback serialisation).
            payload_override: If provided, sent as the POST/PUT body instead of the event.
            notification_urls (list[str]): A list of URLs to send the webhook request to.
            method (str, optional): The HTTP method to use (e.g., "POST", "GET", "PUT", "DELETE").
                                    Defaults to "POST".
            webhook_id (GUID | None, optional): The ID of the webhook being executed (for logging).
            group_id (GUID | None, optional): The ID of the group the webhook belongs to (for logging).
            **_ (Any): Catches any additional keyword arguments (ignored by this publisher).


        Raises:
            ValueError: If an unsupported HTTP method is provided.
            requests.exceptions.HTTPError: If `hard_fail` is True and the request
                                           returns an HTTP error status code after retries.
        """
        if not notification_urls:
            return

        if payload_override is not None:
            event_payload = payload_override
        else:
            event_payload = jsonable_encoder(event, exclude_none=True)
            if "eventType" in event_payload and hasattr(event.event_type, "name"):
                event_payload["eventType"] = event.event_type.name
        http_method = method.upper()

        for url in notification_urls:
            # Retry loop for each URL
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    response: requests.Response | None = None
                    if http_method == "GET":
                        response = requests.get(url, headers=headers, timeout=DEFAULT_WEBHOOK_TIMEOUT)
                    elif http_method == "POST":
                        response = requests.post(url, json=event_payload, headers=headers, timeout=DEFAULT_WEBHOOK_TIMEOUT)
                    elif http_method == "PUT":
                        response = requests.put(url, json=event_payload, headers=headers, timeout=DEFAULT_WEBHOOK_TIMEOUT)
                    elif http_method == "DELETE":
                        response = requests.delete(url, headers=headers, timeout=DEFAULT_WEBHOOK_TIMEOUT)
                    else:
                        raise ValueError(f"Unsupported HTTP method for webhook: {method}")

                    # Check if the request was successful
                    if response is not None:
                        if response.ok:
                            # Capture response body (truncate to 4KB)
                            try:
                                resp_body = response.text[:4096] or None
                            except Exception:
                                resp_body = None
                            _log_webhook_execution(
                                webhook_id=webhook_id,
                                group_id=group_id,
                                status="success",
                                http_status_code=response.status_code,
                                retry_attempt=attempt,
                                request_payload=event_payload if http_method in ("POST", "PUT") else None,
                                response_body=resp_body,
                            )
                            break  # Exit retry loop on success
                        else:
                            # Non-200 status code
                            raise requests.exceptions.HTTPError(f"HTTP {response.status_code}", response=response)

                except (requests.exceptions.RequestException, ValueError) as e:
                    is_last_attempt = attempt == MAX_RETRY_ATTEMPTS - 1
                    failed_response = getattr(e, "response", None)

                    # Capture response body for debugging (truncate to 4KB)
                    resp_body = None
                    if failed_response is not None:
                        try:
                            resp_body = failed_response.text[:4096]
                        except Exception:
                            pass

                    _log_webhook_execution(
                        webhook_id=webhook_id,
                        group_id=group_id,
                        status="failed" if is_last_attempt else "retrying",
                        http_status_code=getattr(failed_response, "status_code", None),
                        error_message=str(e),
                        retry_attempt=attempt,
                        request_payload=event_payload if http_method in ("POST", "PUT") else None,
                        response_body=resp_body,
                    )

                    if is_last_attempt:
                        # Final attempt failed
                        self.logger.error(f"Webhook to {url} failed after {MAX_RETRY_ATTEMPTS} attempts: {e}")
                        if self.hard_fail:
                            raise
                        # Don't retry further, move to next URL
                        break
                    else:
                        # Calculate backoff delay and retry
                        delay = _calculate_retry_delay(attempt)
                        self.logger.warning(f"Webhook to {url} failed (attempt {attempt + 1}/{MAX_RETRY_ATTEMPTS}). Retrying in {delay}s: {e}")
                        time.sleep(delay)


class AuditLogPublisher:
    """
    Publishes events to the event_log database table for audit trail persistence.

    This publisher creates an immutable record of every event that occurs in Marvin,
    enabling event history queries, entity timelines, and user activity tracking.
    """

    def __init__(self) -> None:
        """Initializes the AuditLogPublisher."""
        self.logger = get_logger("audit_log_publisher")

    def publish(self, event: Event, notification_urls: list[str], **_: Any) -> None:
        """
        Persists an event to the event_log table.

        Args:
            event (Event): The event object to persist.
            notification_urls (list[str]): Ignored for audit log publisher (always persists).
            **_ (Any): Catches any additional keyword arguments (ignored).
        """
        try:
            from marvin.db.models.platform.event_log import EventLogModel
            from marvin.repos.repository_factory import AllRepositories

            entity_type, entity_id = event_entity(event)
            operation = None
            if event.document_data and hasattr(event.document_data, "operation"):
                operation = event.document_data.operation.value

            with session_context() as session:
                AllRepositories(session=session, group_id=event.workspace_id)

                log_entry = EventLogModel(
                    event_id=event.event_id,
                    # Store the stable, human-readable name (e.g. "entry_published"), not the
                    # enum's ordinal — matches the schema/API contract and survives enum reordering.
                    event_type=event.event_type.name,
                    occurred_at=event.timestamp,
                    workspace_id=event.workspace_id,
                    user_id=event.user_id,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    integration_id=event.integration_id,
                    operation=operation,
                    correlation_id=getattr(event, "correlation_id", None),
                    event_data=jsonable_encoder(event),
                    message_title=event.message.title,
                    message_body=event.message.body if event.message.body != "generic" else None,
                )

                session.add(log_entry)
                session.commit()
                self.logger.debug(f"Persisted event {event.event_id} ({event.event_type.name}) to audit log")

        except Exception as e:
            self.logger.error(f"Failed to persist event {event.event_id} to audit log: {e}", exc_info=True)
