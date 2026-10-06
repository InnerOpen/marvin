"""
Platform endpoints for querying event logs.

Provides read-only access to the event audit trail for workspace members.
Events can be filtered by type, entity, user, and date range. Platform-scope events (sign-ups, workspaces
created by a platform admin, …) are left out on every route here; the admin Events page lists them.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4, ValidationError

from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.controller import controller
from marvin.schemas.platform.event_log import EventFeed, EventFeedItem, EventLogRead, EventLogSummary
from marvin.services.event_bus_service.event_types import SiteRebuildChange

router = APIRouter(prefix="/events", tags=["Events (Platform)"])

FEED_LIMIT = 50
# The feed answers "since" with a little overlap: an event is stamped when dispatched but written a
# moment later, so one stamped just before the previous poll could land after it. Clients dedupe by
# event_id.
FEED_OVERLAP = timedelta(seconds=10)
# A fresh page asks with no cursor; it gets only the last few seconds, not the backlog.
FEED_FIRST_LOOK = timedelta(seconds=5)
# A site rebuild's "what changed" list, as polled every few seconds: the newest this many.
FEED_MAX_CHANGES = 20


def _document(event_data: dict) -> dict:
    doc = event_data.get("documentData") or event_data.get("document_data") or {}
    return doc if isinstance(doc, dict) else {}


def _detail(event_data: dict) -> str | None:
    doc = _document(event_data)
    reason = doc.get("error") or doc.get("errorMessage") or doc.get("error_message")
    return str(reason)[:500] if reason else None


def _changes(event_data: dict) -> tuple[list[SiteRebuildChange] | None, int | None]:
    """A site rebuild's listed changes (newest last, capped) and its request count; (None, None) otherwise."""
    doc = _document(event_data)
    listed = doc.get("changes")
    if not isinstance(listed, list):
        return None, None
    changes = []
    for item in listed[-FEED_MAX_CHANGES:]:
        try:
            changes.append(SiteRebuildChange.model_validate(item))
        except ValidationError:
            continue  # one malformed line shouldn't hide the rest
    count = doc.get("requestCount", doc.get("request_count"))
    return changes, count if isinstance(count, int) else None


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _progress(event_data: dict) -> dict:
    """What pairs a "running"/"queued" toast with the event that ends it, and what that toast says."""
    doc = _document(event_data)
    run_id = doc.get("executionId")
    return {
        "run_id": str(run_id) if run_id else None,
        "workflow_name": doc.get("automationName") or doc.get("automationSlug"),
        "handled": doc.get("handled") is True,
        "target_count": _int(doc.get("targetCount")),
        "quiet_seconds": _int(doc.get("quietSeconds")),
        "max_wait_seconds": _int(doc.get("maxWaitSeconds")),
    }


def _feed_item(event) -> EventFeedItem:
    event_data = event.event_data or {}
    changes, request_count = _changes(event_data)
    return EventFeedItem(
        **EventLogSummary.model_validate(event).model_dump(),
        detail=_detail(event_data),
        changes=changes,
        request_count=request_count,
        **_progress(event_data),
    )


def build_feed(event_log_repo, workspace_id, since: datetime | None, now: datetime | None = None, visible=None) -> EventFeed:
    now = now or datetime.now(UTC)
    if since is None:
        start = now - FEED_FIRST_LOOK
    else:
        start = (since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)) - FEED_OVERLAP
    events = event_log_repo.get_by_workspace(workspace_id=workspace_id, start_date=start, limit=FEED_LIMIT, visible=visible)
    items = [_feed_item(e) for e in reversed(events)]
    return EventFeed(now=now, events=items)


@controller(router)
class EventsController(BaseUserController):
    """Controller for event log query endpoints.

    Every member sees the workspace's events, except AI-run events (an AI run completing or failing,
    and its approval events, which carry the paused tool calls' arguments): below ADMIN those are only
    the caller's own (services/ai/executions.py), on every route here.
    """

    def _sees_all_runs(self) -> bool:
        from marvin.services.ai.executions import user_sees_every_run

        return user_sees_every_run(self.user, self.group_id)

    def _visible(self):
        from marvin.services.ai.executions import visible_events_clause

        return visible_events_clause(sees_all=self._sees_all_runs(), user_id=self.user.id)

    @router.get("", response_model=list[EventLogSummary])
    def list_events(
        self,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: UUID4 | None = None,
        user_id: UUID4 | None = None,
        correlation_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EventLogSummary]:
        """
        List events for the current workspace with optional filtering.

        Any workspace member can view events for their workspace.

        Query Parameters:
            event_type: Filter by event type (e.g., "entry.published")
            entity_type: Filter by entity type (e.g., "entry", "asset")
            entity_id: Filter by specific entity UUID
            user_id: Filter by user who triggered the event
            start_date: Filter events after this datetime (UTC)
            end_date: Filter events before this datetime (UTC)
            limit: Maximum number of events to return (default 50, max 100)
            offset: Number of events to skip for pagination

        Returns:
            List of event log summaries ordered by occurred_at descending
        """
        # Enforce limit maximum
        if limit > 100:
            limit = 100

        # Query events for this workspace
        events = self.repos.event_log.get_by_workspace(
            workspace_id=self.group_id,
            event_type=event_type,
            entity_type=entity_type,
            user_id=user_id,
            correlation_id=correlation_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
            visible=self._visible(),
        )

        # Filter by entity_id if provided (repo method doesn't support this param yet)
        if entity_id:
            events = [e for e in events if e.entity_id == entity_id]

        # Convert to summary schema (lighter payload)
        return [EventLogSummary.model_validate(e) for e in events]

    @router.get("/feed", response_model=EventFeed)
    def event_feed(self, since: datetime | None = None) -> EventFeed:
        """
        What happened in the current workspace since `since` (UTC), oldest first — the admin's
        activity toaster polls this. Pass the previous response's `now` as the next `since`.
        Returns at most the newest FEED_LIMIT events.
        """
        return build_feed(self.repos.event_log, self.group_id, since, visible=self._visible())

    @router.get("/{event_id}", response_model=EventLogRead)
    def get_event(
        self,
        event_id: UUID4,
    ) -> EventLogRead:
        """
        Get a single event by its event_id.

        Any workspace member can view events for their workspace.

        Args:
            event_id: The event_id (not the database ID) to retrieve

        Returns:
            Complete event log entry with full payload

        Raises:
            HTTPException: 404 if event not found or not in current workspace
        """
        from marvin.services.ai.executions import may_see_event
        from marvin.services.events.event_catalog import is_platform_event

        event = self.repos.event_log.get_by_event_id(event_id)

        # A platform event (the admin Events page's) isn't in the workspace's log: the same 404 as a missing one.
        if event and is_platform_event(event.event_type):
            event = None

        # Another member's AI-run event, below ADMIN, is the same 404 as a missing one.
        if event and event.workspace_id == self.group_id and not may_see_event(event, sees_all=self._sees_all_runs(), user_id=self.user.id):
            event = None

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event {event_id} not found.",
            )

        # Verify event belongs to current workspace
        if event.workspace_id != self.group_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this event.",
            )

        return event

    @router.get("/entity/{entity_id}", response_model=list[EventLogSummary])
    def get_entity_history(
        self,
        entity_id: UUID4,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EventLogSummary]:
        """
        Get complete event history for a specific entity (entry, asset, etc.).

        Any workspace member can view entity history for their workspace.

        Args:
            entity_id: The UUID of the entity
            entity_type: Optional entity type filter (e.g., "entry", "asset")
            limit: Maximum number of events to return (default 50, max 100)
            offset: Number of events to skip for pagination

        Returns:
            List of events for this entity ordered by occurred_at descending
        """
        # Enforce limit maximum
        if limit > 100:
            limit = 100

        # Get events for this entity
        events = self.repos.event_log.get_by_entity(
            entity_id=entity_id,
            entity_type=entity_type,
            limit=limit,
            offset=offset,
            visible=self._visible(),
        )

        # Filter to only events in current workspace
        events = [e for e in events if e.workspace_id == self.group_id]

        # Convert to summary schema
        return [EventLogSummary.model_validate(e) for e in events]

    @router.get("/user/{user_id}", response_model=list[EventLogSummary])
    def get_user_activity(
        self,
        user_id: UUID4,
        event_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EventLogSummary]:
        """
        Get activity history for a specific user in the current workspace.

        Any workspace member can view user activity for their workspace.

        Args:
            user_id: The UUID of the user
            event_type: Optional event type filter (e.g., "entry.published")
            start_date: Filter events after this datetime (UTC)
            end_date: Filter events before this datetime (UTC)
            limit: Maximum number of events to return (default 50, max 100)
            offset: Number of events to skip for pagination

        Returns:
            List of events triggered by this user ordered by occurred_at descending
        """
        # Enforce limit maximum
        if limit > 100:
            limit = 100

        # Get events for this user
        events = self.repos.event_log.get_by_user(
            user_id=user_id,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
            visible=self._visible(),
        )

        # Filter to only events in current workspace
        events = [e for e in events if e.workspace_id == self.group_id]

        # Convert to summary schema
        return [EventLogSummary.model_validate(e) for e in events]
