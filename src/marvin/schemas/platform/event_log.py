"""Event log schemas."""

from datetime import datetime

from pydantic import UUID4, ConfigDict

from marvin.schemas._marvin import _MarvinModel
from marvin.services.event_bus_service.event_types import SiteRebuildChange


class EventLogRead(_MarvinModel):
    """Schema for reading an event log entry."""

    id: UUID4
    event_id: UUID4
    event_type: str
    occurred_at: datetime
    workspace_id: UUID4
    user_id: UUID4 | None = None
    entity_id: UUID4 | None = None
    entity_type: str | None = None
    integration_id: str
    operation: str | None = None
    correlation_id: str | None = None  # chain id — group an event with its whole causal cascade
    event_data: dict
    message_title: str
    message_body: str | None = None
    created_at: datetime | None = None
    update_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class EventLogSummary(_MarvinModel):
    """Summary schema for an event log entry (lighter payload)."""

    id: UUID4
    event_id: UUID4
    event_type: str
    occurred_at: datetime
    workspace_id: UUID4 | None = None
    """None for a platform event with no workspace (a backup target's run)."""
    user_id: UUID4 | None = None
    entity_id: UUID4 | None = None
    entity_type: str | None = None
    correlation_id: str | None = None  # chain id — follow a cascade across events
    message_title: str
    message_body: str | None = None
    related_entity_type: str | None = None
    """A second subject the event names beside its entity — on a workflow run, what triggered it."""
    related_entity_id: str | None = None
    related_entity_label: str | None = None
    """The related subject's name as the event recorded it (e.g. the entry's title)."""

    model_config = ConfigDict(from_attributes=True)


class EventFeedItem(EventLogSummary):
    """An event as the admin's live activity toaster shows it."""

    detail: str | None = None
    """Why it failed, when the event carries a reason (e.g. a failed workflow's error)."""
    changes: list[SiteRebuildChange] | None = None
    """What a site rebuild covers, newest last (capped) — None for any other event."""
    request_count: int | None = None
    """How many requests that rebuild covers; more than len(changes) when repeats collapsed or the list was capped."""
    run_id: str | None = None
    """A workflow run's id on automation_started / automation_ran / automation_failed — the toaster
    updates one toast per run."""
    workflow_name: str | None = None
    """The workflow's display name (falls back to its slug) on those events."""
    handled: bool = False
    """A failed workflow run whose failures the integration's error policy took care of (sent to
    review, retry scheduled, …) — the toaster shows it as a warning instead of an error."""
    target_count: int | None = None
    """How many entries a target-query run acts on (automation_started)."""
    quiet_seconds: int | None = None
    """A queued site rebuild is sent once requests have been quiet this long (site_rebuild_queued)."""
    max_wait_seconds: int | None = None
    """…or at the latest this long after its first request (site_rebuild_queued)."""


class EventFeed(_MarvinModel):
    """Events since a cursor, oldest first, plus the server's clock to poll from next."""

    now: datetime
    events: list[EventFeedItem]
