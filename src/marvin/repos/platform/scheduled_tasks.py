"""Scheduled tasks repository."""

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import UUID4
from slugify import slugify
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from marvin.db.models.platform.scheduled_tasks import (
    ScheduledTaskExecutionLogModel,
    ScheduledTaskModel,
)
from marvin.repos.repository_generic import GroupRepositoryGeneric
from marvin.schemas.platform.scheduled_tasks import (
    ScheduledTaskExecutionLogRead,
    ScheduledTaskRead,
)


class ScheduledTasksRepository(GroupRepositoryGeneric[ScheduledTaskRead, ScheduledTaskModel]):
    """Repository for managing scheduled tasks."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=ScheduledTaskModel,
            schema=ScheduledTaskRead,
            group_id=group_id,
        )

    def create(self, data: Any) -> ScheduledTaskRead:
        """Create a new scheduled task."""
        data_dict = data if isinstance(data, dict) else data.model_dump()
        if self.group_id:
            data_dict["group_id"] = self.group_id

        # Auto-generate slug from name if not provided
        if not data_dict.get("slug") and data_dict.get("name"):
            data_dict["slug"] = slugify(data_dict["name"])

        # Calculate initial next_run_at from schedule
        if not data_dict.get("next_run_at"):
            data_dict["next_run_at"] = self._compute_next_run(data_dict.get("schedule_type"), data_dict.get("schedule_config"))

        return super().create(data_dict)

    def update(self, match_value: Any, new_data: Any, match_key: str | None = None) -> ScheduledTaskRead:
        """Update a scheduled task."""
        data_dict = new_data if isinstance(new_data, dict) else new_data.model_dump(exclude_unset=True)

        # Don't allow updating slug or group_id
        data_dict.pop("slug", None)
        data_dict.pop("group_id", None)

        # Recalculate next_run_at when schedule changes
        if "schedule_type" in data_dict or "schedule_config" in data_dict:
            existing = self.get_one(match_value)
            schedule_type = data_dict.get("schedule_type") or (existing.schedule_type if existing else None)
            schedule_config = data_dict.get("schedule_config") or (existing.schedule_config if existing else None)
            data_dict["next_run_at"] = self._compute_next_run(schedule_type, schedule_config)

        return super().update(match_value, data_dict, match_key=match_key)

    @staticmethod
    def _compute_next_run(schedule_type: str | None, schedule_config: dict | None) -> datetime | None:
        """Calculate next_run_at from schedule type and config."""
        if not schedule_type or not schedule_config:
            return None
        now = datetime.now(UTC)
        if schedule_type == "once":
            run_at = schedule_config.get("run_at")
            if run_at:
                if isinstance(run_at, str):
                    dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
                    return dt.astimezone(UTC).replace(tzinfo=None)
                return run_at
        elif schedule_type == "interval":
            seconds = schedule_config.get("interval_seconds")
            if seconds:
                return now + timedelta(seconds=int(seconds))
        elif schedule_type == "cron":
            from marvin.services import cron

            return cron.next_run(schedule_config.get("cron_expression"), schedule_config.get("timezone"))
        return None

    def schedule_unscheduled_cron(self) -> int:
        """Give enabled cron tasks with no next_run_at their next run; returns how many were scheduled.

        Cron used to compute no next run at all, so those tasks never became due — and only a run recomputes it.
        A task whose stored cron can't run (see services.cron.problem) stays unscheduled.
        """
        stmt = select(ScheduledTaskModel).where(
            and_(
                ScheduledTaskModel.enabled == True,  # noqa: E712
                ScheduledTaskModel.schedule_type == "cron",
                ScheduledTaskModel.next_run_at.is_(None),
            )
        )
        scheduled = 0
        for task in self.session.execute(stmt).scalars().all():
            next_run = self._compute_next_run(task.schedule_type, task.schedule_config)
            if next_run is not None:
                task.next_run_at = next_run
                scheduled += 1
        if scheduled:
            self.session.commit()
        return scheduled

    def get_due_tasks(self, now: datetime) -> list[ScheduledTaskRead]:
        """
        Find tasks that are due to run.

        Args:
            now: Current timestamp (UTC)

        Returns:
            List of enabled tasks where next_run_at <= now, ordered by next_run_at
        """
        stmt = (
            select(ScheduledTaskModel)
            .where(
                and_(
                    ScheduledTaskModel.enabled == True,  # noqa: E712
                    ScheduledTaskModel.next_run_at <= now,
                )
            )
            .order_by(ScheduledTaskModel.next_run_at)
        )

        results = self.session.execute(stmt).scalars().all()
        return [ScheduledTaskRead.model_validate(r) for r in results]

    def update_next_run(self, task_id: UUID4, next_run: datetime | None) -> None:
        """
        Update next_run_at after execution.

        Args:
            task_id: Task ID to update
            next_run: Next scheduled run time (UTC)
        """
        task = self.session.get(ScheduledTaskModel, task_id)
        if task:
            task.next_run_at = next_run
            self.session.commit()

    def update_execution_state(
        self,
        task_id: UUID4,
        last_run_at: datetime,
        last_status: str,
        last_duration_ms: int | None = None,
        failure_count: int = 0,
    ) -> None:
        """
        Update task execution state after a run.

        Args:
            task_id: Task ID to update
            last_run_at: Timestamp of last execution
            last_status: Status of last execution
            last_duration_ms: Duration in milliseconds
            failure_count: Updated failure count
        """
        task = self.session.get(ScheduledTaskModel, task_id)
        if task:
            task.last_run_at = last_run_at
            task.last_status = last_status
            task.last_duration_ms = last_duration_ms
            task.failure_count = failure_count
            self.session.commit()

    def get_by_slug(self, slug: str) -> ScheduledTaskRead | None:
        """
        Get a task by its slug.

        Args:
            slug: Task slug

        Returns:
            ScheduledTaskRead if found, None otherwise
        """
        stmt = select(ScheduledTaskModel).where(
            and_(
                ScheduledTaskModel.slug == slug,
                ScheduledTaskModel.group_id == self.group_id,
            )
        )
        result = self.session.execute(stmt).scalars().first()
        return ScheduledTaskRead.model_validate(result) if result else None


class ScheduledTaskExecutionLogRepository(GroupRepositoryGeneric[ScheduledTaskExecutionLogRead, ScheduledTaskExecutionLogModel]):
    """Repository for scheduled task execution logs."""

    def __init__(self, session: Session, group_id: UUID4 | None) -> None:
        super().__init__(
            session=session,
            primary_key="id",
            sql_model=ScheduledTaskExecutionLogModel,
            schema=ScheduledTaskExecutionLogRead,
            group_id=group_id,
        )

    def log_execution(
        self,
        task_id: UUID4,
        group_id: UUID4 | None,
        status: str,
        executed_at: datetime,
        duration_ms: int | None = None,
        error_message: str | None = None,
        error_traceback: str | None = None,
        output: str | None = None,
        retry_attempt: int = 0,
    ) -> ScheduledTaskExecutionLogRead:
        """
        Record a task execution.

        Args:
            task_id: ID of the task that executed
            group_id: Workspace ID (can be None for system tasks)
            status: Execution status ('success', 'failed', 'timeout', 'cancelled')
            executed_at: Timestamp when execution started
            duration_ms: Execution duration in milliseconds
            error_message: Error message if failed
            error_traceback: Full traceback if failed
            retry_attempt: Retry attempt number (0 = first attempt)

        Returns:
            Created execution log entry
        """
        log_entry = ScheduledTaskExecutionLogModel(
            session=self.session,
            task_id=task_id,
            group_id=group_id,
            status=status,
            executed_at=executed_at,
            duration_ms=duration_ms,
            error_message=error_message,
            error_traceback=error_traceback,
            output=output,
            retry_attempt=retry_attempt,
        )
        self.session.add(log_entry)
        self.session.commit()

        return ScheduledTaskExecutionLogRead.model_validate(log_entry)

    def get_task_history(
        self,
        task_id: UUID4,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ScheduledTaskExecutionLogRead]:
        """
        Get execution history for a task.

        Args:
            task_id: Task ID to query
            limit: Maximum number of logs to return
            offset: Number of logs to skip

        Returns:
            List of execution logs, ordered by executed_at descending
        """
        stmt = (
            select(ScheduledTaskExecutionLogModel)
            .where(ScheduledTaskExecutionLogModel.task_id == task_id)
            .order_by(ScheduledTaskExecutionLogModel.executed_at.desc())
            .limit(limit)
            .offset(offset)
        )

        results = self.session.execute(stmt).scalars().all()
        return [ScheduledTaskExecutionLogRead.model_validate(r) for r in results]

    def get_workspace_log(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ScheduledTaskExecutionLogRead]:
        """
        Get all execution logs for this workspace, ordered by executed_at descending.

        When group_id is None (admin context), returns logs across all workspaces.
        """
        stmt = select(ScheduledTaskExecutionLogModel).order_by(ScheduledTaskExecutionLogModel.executed_at.desc()).limit(limit).offset(offset)

        if self.group_id:
            stmt = stmt.where(ScheduledTaskExecutionLogModel.group_id == self.group_id)

        results = self.session.execute(stmt).scalars().all()
        return [ScheduledTaskExecutionLogRead.model_validate(r) for r in results]

    def get_recent_failures(
        self,
        limit: int = 20,
        hours: int = 24,
    ) -> list[ScheduledTaskExecutionLogRead]:
        """
        Get recent failed executions across all tasks.

        Args:
            limit: Maximum number of failures to return
            hours: Number of hours to look back

        Returns:
            List of failed execution logs, ordered by executed_at descending
        """
        cutoff = datetime.now(UTC) - timedelta(hours=hours)

        stmt = (
            select(ScheduledTaskExecutionLogModel)
            .where(
                and_(
                    ScheduledTaskExecutionLogModel.status == "failed",
                    ScheduledTaskExecutionLogModel.executed_at >= cutoff,
                )
            )
            .order_by(ScheduledTaskExecutionLogModel.executed_at.desc())
            .limit(limit)
        )

        if self.group_id:
            stmt = stmt.where(ScheduledTaskExecutionLogModel.group_id == self.group_id)

        results = self.session.execute(stmt).scalars().all()
        return [ScheduledTaskExecutionLogRead.model_validate(r) for r in results]
