"""Scheduled tasks schemas."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import UUID4, ConfigDict, Field, StringConstraints, model_validator

from marvin.schemas._marvin import _MarvinModel


class ScheduledTaskCreate(_MarvinModel):
    """Schema for creating a new scheduled task."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """Human-readable task name."""

    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    """URL-friendly slug. Auto-generated from name if not provided."""

    description: str | None = None
    """Optional description of what this task does."""

    enabled: bool = True
    """Whether this task is active and should run."""

    schedule_type: Literal["cron", "interval", "once"]
    """Type of schedule: cron expression, interval in seconds, or one-time execution."""

    schedule_config: dict
    """
    Schedule configuration based on schedule_type:
    - cron: {cron_expression: str, timezone: str (default: UTC)}
    - interval: {interval_seconds: int, timezone: str (optional)}
    - once: {run_at: datetime (ISO 8601)}
    """

    task_type: str
    """Task type identifier (e.g., 'publish', 'cleanup', 'metadata_extraction')."""

    task_config: dict = Field(default_factory=dict)
    """Task-specific configuration parameters."""

    retry_policy: dict | None = None
    """
    Optional retry policy:
    {
        max_retries: int,
        backoff_multiplier: float,
        timeout_seconds: int
    }
    """

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _cron_can_run(self):
        # A cron schedule the scheduler can't compute would be saved and then never run.
        if self.schedule_type == "cron" and self.schedule_config is not None:
            from marvin.services import cron

            problem = cron.problem(self.schedule_config.get("cron_expression"), self.schedule_config.get("timezone"))
            if problem:
                raise ValueError(problem)
        return self


class ScheduledTaskUpdate(_MarvinModel):
    """Schema for updating a scheduled task."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    """Human-readable task name."""

    description: str | None = None
    """Optional description of what this task does."""

    enabled: bool | None = None
    """Whether this task is active and should run."""

    schedule_type: Literal["cron", "interval", "once"] | None = None
    """Type of schedule."""

    schedule_config: dict | None = None
    """Schedule configuration."""

    task_config: dict | None = None
    """Task-specific configuration parameters."""

    retry_policy: dict | None = None
    """Optional retry policy."""

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _cron_can_run(self):
        # A cron schedule the scheduler can't compute would be saved and then never run.
        if self.schedule_type == "cron" and self.schedule_config is not None:
            from marvin.services import cron

            problem = cron.problem(self.schedule_config.get("cron_expression"), self.schedule_config.get("timezone"))
            if problem:
                raise ValueError(problem)
        return self


class ScheduledTaskSummary(_MarvinModel):
    """Summary schema for a scheduled task."""

    id: UUID4
    """Unique identifier."""

    name: str
    """Human-readable task name."""

    slug: str
    """URL-friendly slug."""

    description: str | None = None
    """Optional description."""

    enabled: bool
    """Whether this task is active."""

    schedule_type: str
    """Type of schedule: cron, interval, or once."""

    task_type: str
    """Task type identifier."""

    last_run_at: datetime | None = None
    """Timestamp of last execution (UTC)."""

    next_run_at: datetime | None = None
    """Timestamp of next scheduled execution (UTC)."""

    last_status: str | None = None
    """Status of last execution: success, failed, timeout, cancelled."""

    failure_count: int
    """Consecutive failure count."""

    created_at: datetime | None = None
    """Timestamp when the task was created."""

    update_at: datetime | None = None
    """Timestamp when the task was last updated."""

    model_config = ConfigDict(from_attributes=True)


class ScheduledTaskRead(ScheduledTaskSummary):
    """Full schema for reading a scheduled task."""

    group_id: UUID4 | None = None
    """Workspace ID (NULL = system-wide task)."""

    schedule_config: dict
    """Schedule configuration."""

    task_config: dict
    """Task-specific configuration parameters."""

    retry_policy: dict | None = None
    """Optional retry policy."""

    last_duration_ms: int | None = None
    """Duration of last execution in milliseconds."""

    source_integration_id: UUID4 | None = None
    """Read-only "installed by": the integration whose blueprint created this (null: made by a person)."""
    source_blueprint: str | None = None
    """Read-only: the slug of the blueprint that created this, if one did."""

    model_config = ConfigDict(from_attributes=True)


class ScheduledTaskExecutionLogRead(_MarvinModel):
    """Schema for reading a scheduled task execution log entry."""

    id: UUID4
    """Unique identifier."""

    task_id: UUID4
    """Reference to the scheduled task."""

    group_id: UUID4 | None = None
    """Workspace ID (denormalized from task)."""

    executed_at: datetime
    """Timestamp when execution started (UTC)."""

    status: str
    """Execution status: success, failed, timeout, cancelled."""

    duration_ms: int | None = None
    """Execution duration in milliseconds."""

    error_message: str | None = None
    """Error message if execution failed."""

    error_traceback: str | None = None
    """Full error traceback for debugging."""

    output: str | None = None
    """Human-readable summary of what the handler did."""

    retry_attempt: int
    """Retry attempt number (0 = first attempt)."""

    model_config = ConfigDict(from_attributes=True)
