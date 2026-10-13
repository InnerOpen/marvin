"""
Scheduled Tasks database models for platform automation.

This module provides the database models for Marvin's scheduled task subsystem,
enabling proactive automation by executing tasks on a schedule.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from marvin.db.models import BaseMixins, SqlAlchemyBase

from .._model_utils.auto_init import auto_init
from .._model_utils.guid import GUID
from .._model_utils.installed_by import InstalledByMixin


class ScheduledTaskModel(SqlAlchemyBase, BaseMixins, InstalledByMixin):
    """
    Scheduled task model for platform automation.

    Represents a task that runs on a schedule (cron, interval, or once) to perform
    automated operations like publishing, cleanup, or asset processing.

    Tasks are scoped to a workspace (group_id) or system-wide (group_id=None).
    The scheduler checks for due tasks and dispatches events to trigger execution.
    """

    __tablename__ = "scheduled_tasks"

    # Identity
    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    group_id: Mapped[GUID | None] = mapped_column(
        GUID,
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """Workspace ID (NULL = system-wide task)."""

    # Metadata
    name: Mapped[str] = mapped_column(String, nullable=False)
    """Human-readable task name."""

    slug: Mapped[str] = mapped_column(String, nullable=False)
    """URL-safe unique identifier within workspace."""

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Optional task description."""

    # Scheduling
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Whether this task is active."""

    schedule_type: Mapped[str] = mapped_column(String, nullable=False)
    """Schedule type: 'cron', 'interval', or 'once'."""

    schedule_config: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    """Schedule configuration (cron_expression, interval_seconds, timezone, etc.)."""

    # Execution state
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Timestamp of last execution (UTC)."""

    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    """Timestamp of next scheduled execution (UTC)."""

    last_status: Mapped[str | None] = mapped_column(String, nullable=True)
    """Status of last execution: 'success', 'failed', 'timeout', 'cancelled'."""

    last_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Duration of last execution in milliseconds."""

    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    """Consecutive failure count (reset on success)."""

    # Task definition
    task_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    """Task type identifier (e.g., 'publish', 'cleanup', 'metadata_extraction')."""

    task_config: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict, server_default="{}")
    """Task-specific configuration parameters."""

    retry_policy: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    """Retry policy: {max_retries, backoff_multiplier, timeout_seconds}."""

    __table_args__ = (
        UniqueConstraint("group_id", "slug", name="uq_scheduled_tasks_group_slug"),
        Index("ix_scheduled_tasks_next_run", "next_run_at", "enabled"),
        Index("ix_scheduled_tasks_workspace", "group_id", "enabled"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass


class ScheduledTaskExecutionLogModel(SqlAlchemyBase):
    """
    Execution log for scheduled tasks.

    Records each execution attempt with status, duration, and error details.
    Provides historical tracking for debugging and monitoring.
    """

    __tablename__ = "scheduled_task_execution_log"

    # Identity
    id: Mapped[GUID] = mapped_column(GUID, primary_key=True, default=GUID.generate)
    task_id: Mapped[GUID] = mapped_column(
        GUID,
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """Reference to the scheduled task."""

    group_id: Mapped[GUID | None] = mapped_column(
        GUID,
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """Workspace ID (denormalized from task for efficient queries)."""

    # Execution details
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    """Timestamp when execution started (UTC)."""

    status: Mapped[str] = mapped_column(String, nullable=False)
    """Execution status: 'success', 'failed', 'timeout', 'cancelled'."""

    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Execution duration in milliseconds."""

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Error message if execution failed."""

    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Full error traceback for debugging."""

    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Human-readable summary of what the handler did (e.g. '3 files deleted, 4.2 KB freed')."""

    retry_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    """Retry attempt number (0 = first attempt)."""

    __table_args__ = (
        Index("ix_task_execution_task_time", "task_id", "executed_at"),
        Index("ix_task_execution_workspace_time", "group_id", "executed_at"),
    )

    @auto_init()
    def __init__(self, session: Session, **kwargs) -> None:
        """Initialize via Marvin's auto-init model helper."""
        pass
