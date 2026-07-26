"""
Event Log database model for persisting all platform events.

This model creates an audit trail of all events that occur within workspaces,
enabling event history queries, entity timelines, and user activity tracking.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from marvin.db.models import BaseMixins, SqlAlchemyBase

from .._model_utils.guid import GUID


class EventLogModel(SqlAlchemyBase, BaseMixins):
    """
    Event log model for persisting all platform events.

    This table creates a complete audit trail of everything that happens in Marvin.
    Events are immutable once created - they represent facts that already occurred.

    The event_data sa.JSON column contains the full event payload for queryability,
    while message_title and message_body provide human-readable summaries.
    """

    __tablename__ = "event_log"

    # Primary identifiers
    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    event_id: Mapped[GUID] = mapped_column(GUID, unique=True, index=True, nullable=False)
    """Unique event ID from the original Event object."""

    event_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    """Event type (e.g., 'entry.published', 'asset.uploaded')."""

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    """Timestamp when the event occurred (UTC)."""

    # Core identifiers for filtering and relationships
    workspace_id: Mapped[GUID | None] = mapped_column(GUID, ForeignKey("groups.id"), index=True, nullable=True)
    """The workspace this event pertains to (None for platform/system-scoped events, e.g. a global scheduled task)."""

    user_id: Mapped[GUID | None] = mapped_column(GUID, ForeignKey("users.id"), index=True, nullable=True)
    """The user who triggered this event (None for system events)."""

    entity_id: Mapped[GUID | None] = mapped_column(GUID, index=True, nullable=True)
    """The ID of the primary entity this event is about (entry, asset, etc.)."""

    entity_type: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    """The type of the primary entity (entry, asset, workspace, etc.)."""

    # Event metadata
    integration_id: Mapped[str] = mapped_column(String, nullable=False)
    """Identifier for the system/integration that generated the event."""

    operation: Mapped[str | None] = mapped_column(String, nullable=True)
    """The operation type (create, update, delete, info)."""

    correlation_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    """Id shared by every event + execution in one causal chain — so a whole reaction cascade
    (user action → automation → re-emitted event → …) is queryable as one thread. See
    services/event_bus_service/correlation.py."""

    # Full event payload (sa.JSON for queryability)
    event_data: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    """Complete event payload as JSON for rich queries."""

    # Human-readable summary
    message_title: Mapped[str] = mapped_column(String, nullable=False)
    """Human-readable event title."""

    message_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Human-readable event description."""

    __table_args__ = (
        # Composite index for common query pattern: workspace events by type and time
        Index(
            "ix_event_log_workspace_type_time",
            "workspace_id",
            "event_type",
            "occurred_at",
        ),
        # Composite index for user activity queries
        Index("ix_event_log_user_time", "user_id", "occurred_at"),
        # Composite index for entity history queries
        Index("ix_event_log_entity", "entity_id", "entity_type", "occurred_at"),
    )
