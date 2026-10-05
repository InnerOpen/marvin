"""Event log repository."""

from datetime import datetime

from pydantic import UUID4
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from marvin.db.models.platform.event_log import EventLogModel
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform.event_log import EventLogRead


class EventLogRepository(GroupRepositoryGeneric):
    """Repository for querying event logs."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=EventLogModel,
            schema=EventLogRead,
            group_id=group_id,
        )

    def get_by_event_id(self, event_id: UUID4) -> EventLogRead | None:
        """
        Get an event log entry by its event_id.

        Args:
            event_id: The event_id to search for

        Returns:
            EventLogRead if found, None otherwise
        """
        stmt = select(EventLogModel).where(EventLogModel.event_id == event_id)
        result = self.session.execute(stmt).scalars().first()
        return EventLogRead.model_validate(result) if result else None

    def prune_older_than(self, cutoff: datetime) -> int:
        """Delete event_log rows older than `cutoff` (across all workspaces). Returns rows deleted."""
        from sqlalchemy import delete

        result = self.session.execute(delete(EventLogModel).where(EventLogModel.occurred_at < cutoff))
        self.session.commit()
        return result.rowcount or 0

    def get_by_entity(
        self,
        entity_id: UUID4,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        visible=None,
    ) -> list[EventLogRead]:
        """
        Get all events for a specific entity.

        Args:
            entity_id: The entity ID to query
            entity_type: Optional entity type filter (e.g., "entry", "asset")
            limit: Maximum number of events to return
            offset: Number of events to skip
            visible: Optional extra WHERE condition limiting what the caller may see
                (services.ai.executions.visible_events_clause)

        Returns:
            List of events for the entity, ordered by occurred_at descending
        """
        stmt = select(EventLogModel).where(EventLogModel.entity_id == entity_id).order_by(desc(EventLogModel.occurred_at)).limit(limit).offset(offset)

        if entity_type:
            stmt = stmt.where(EventLogModel.entity_type == entity_type)

        if visible is not None:  # services.ai.executions.visible_events_clause: the caller's view
            stmt = stmt.where(visible)

        results = self.session.execute(stmt).scalars().all()
        return [EventLogRead.model_validate(r) for r in results]

    def get_by_user(
        self,
        user_id: UUID4,
        event_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
        visible=None,
    ) -> list[EventLogRead]:
        """
        Get all events triggered by a specific user.

        Args:
            user_id: The user ID to query
            event_type: Optional event type filter (e.g., "entry.published")
            start_date: Optional start date filter (UTC)
            end_date: Optional end date filter (UTC)
            limit: Maximum number of events to return
            offset: Number of events to skip
            visible: Optional extra WHERE condition limiting what the caller may see
                (services.ai.executions.visible_events_clause)

        Returns:
            List of events triggered by the user, ordered by occurred_at descending
        """
        stmt = select(EventLogModel).where(EventLogModel.user_id == user_id).order_by(desc(EventLogModel.occurred_at)).limit(limit).offset(offset)

        if event_type:
            stmt = stmt.where(EventLogModel.event_type == event_type)

        if start_date:
            stmt = stmt.where(EventLogModel.occurred_at >= start_date)

        if end_date:
            stmt = stmt.where(EventLogModel.occurred_at <= end_date)

        if visible is not None:  # services.ai.executions.visible_events_clause: the caller's view
            stmt = stmt.where(visible)

        results = self.session.execute(stmt).scalars().all()
        return [EventLogRead.model_validate(r) for r in results]

    def get_by_workspace(
        self,
        workspace_id: UUID4,
        event_type: str | None = None,
        entity_type: str | None = None,
        user_id: UUID4 | None = None,
        correlation_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
        visible=None,
    ) -> list[EventLogRead]:
        """
        Get events for a workspace with optional filters.

        Args:
            workspace_id: The workspace ID to query
            event_type: Optional event type filter (e.g., "entry.published")
            entity_type: Optional entity type filter (e.g., "entry", "asset")
            user_id: Optional user ID filter
            correlation_id: Optional chain filter — every event in one causal cascade
            start_date: Optional start date filter (UTC)
            end_date: Optional end date filter (UTC)
            limit: Maximum number of events to return
            offset: Number of events to skip
            visible: Optional extra WHERE condition limiting what the caller may see
                (services.ai.executions.visible_events_clause)

        Returns:
            List of events matching the filters, ordered by occurred_at descending
        """
        stmt = (
            select(EventLogModel)
            .where(EventLogModel.workspace_id == workspace_id)
            .order_by(desc(EventLogModel.occurred_at))
            .limit(limit)
            .offset(offset)
        )

        if event_type:
            stmt = stmt.where(EventLogModel.event_type == event_type)

        if entity_type:
            stmt = stmt.where(EventLogModel.entity_type == entity_type)

        if user_id:
            stmt = stmt.where(EventLogModel.user_id == user_id)

        if correlation_id:
            stmt = stmt.where(EventLogModel.correlation_id == correlation_id)

        if start_date:
            stmt = stmt.where(EventLogModel.occurred_at >= start_date)

        if end_date:
            stmt = stmt.where(EventLogModel.occurred_at <= end_date)

        if visible is not None:  # services.ai.executions.visible_events_clause: the caller's view
            stmt = stmt.where(visible)

        results = self.session.execute(stmt).scalars().all()
        return [EventLogRead.model_validate(r) for r in results]
