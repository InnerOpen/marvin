"""
Scheduled tasks platform API controller.

Provides CRUD endpoints for managing scheduled tasks, viewing execution history,
and manually triggering task execution. Workspace-admin only, like workflows, except the
task-type catalog: a task runs handlers the automation engine reserves for ADMIN.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import UUID4

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin
from marvin.schemas.platform.scheduled_tasks import (
    ScheduledTaskCreate,
    ScheduledTaskExecutionLogRead,
    ScheduledTaskRead,
    ScheduledTaskUpdate,
)
from marvin.services.event_bus_service.event_types import EventScheduledTaskData, EventTypes

router = APIRouter(prefix="/scheduled-tasks", tags=["Platform: Scheduled Tasks"])


@controller(router)
class ScheduledTasksController(BaseUserController):
    """Controller for scheduled task CRUD operations."""

    @router.get("/task-types")
    def list_task_types(self, detailed: bool = False):
        """
        List task types available to workspace users (excludes admin-only types).

        Args:
            detailed: If True, return full metadata including config schemas
        """
        from marvin.services.scheduled_tasks import TaskHandlerRegistry

        if detailed:
            return [t for t in TaskHandlerRegistry.get_task_type_info() if not t.get("admin_only")]
        return list(TaskHandlerRegistry.list_registered_types(include_admin=False))

    @router.get("", response_model=list[ScheduledTaskRead])
    def list_tasks(self):
        """List all scheduled tasks for the current workspace."""
        require_workspace_admin(self.user, self.group_id)
        return self.repos.scheduled_tasks.get_all(order_by="name")

    @router.post("", response_model=ScheduledTaskRead, status_code=status.HTTP_201_CREATED)
    def create_task(self, data: ScheduledTaskCreate):
        """Create a new scheduled task."""
        require_workspace_admin(self.user, self.group_id)

        # Create the task
        task = self.repos.scheduled_tasks.create(data)

        # Emit event
        self.event_bus.dispatch(
            integration_id="platform_api",
            group_id=self.group_id,
            event_type=EventTypes.scheduled_task_created,
            document_data=EventScheduledTaskData.from_model(task, workspace_name=self.group.name if self.group else None),
            message=f"Scheduled task '{task.name}' created",
            entity_id=task.id,
            entity_type="scheduled_task",
        )

        return task

    @router.get("/log", response_model=list[ScheduledTaskExecutionLogRead])
    def get_workspace_log(self, limit: int = 100):
        """Get execution log for all tasks in the current workspace."""
        require_workspace_admin(self.user, self.group_id)
        return self.repos.scheduled_task_executions.get_workspace_log(limit=limit)

    @router.get("/{id_or_slug}", response_model=ScheduledTaskRead)
    def get_task(self, id_or_slug: Annotated[str, Path()]):
        """Get a scheduled task by ID or slug."""
        require_workspace_admin(self.user, self.group_id)
        # Try UUID first
        try:
            uuid_val = UUID4(id_or_slug)
            task = self.repos.scheduled_tasks.get_one(uuid_val)
        except ValueError:
            # Try slug
            task = self.repos.scheduled_tasks.get_by_slug(id_or_slug)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scheduled task '{id_or_slug}' not found",
            )

        return task

    @router.patch("/{id_or_slug}", response_model=ScheduledTaskRead)
    def update_task(self, id_or_slug: Annotated[str, Path()], data: ScheduledTaskUpdate):
        """Update a scheduled task."""
        require_workspace_admin(self.user, self.group_id)
        # Try UUID first
        try:
            uuid_val = UUID4(id_or_slug)
            task = self.repos.scheduled_tasks.update(uuid_val, data)
        except ValueError:
            # Try slug
            found = self.repos.scheduled_tasks.get_by_slug(id_or_slug)
            if not found:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Scheduled task '{id_or_slug}' not found",
                ) from None
            task = self.repos.scheduled_tasks.update(found.id, data)

        # Emit event
        self.event_bus.dispatch(
            integration_id="platform_api",
            group_id=self.group_id,
            event_type=EventTypes.scheduled_task_updated,
            document_data=EventScheduledTaskData.from_model(task, workspace_name=self.group.name if self.group else None),
            message=f"Scheduled task '{task.name}' updated",
            entity_id=task.id,
            entity_type="scheduled_task",
        )

        return task

    @router.delete("/{id_or_slug}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_task(self, id_or_slug: Annotated[str, Path()]):
        """Delete a scheduled task."""
        require_workspace_admin(self.user, self.group_id)
        # Try UUID first
        try:
            uuid_val = UUID4(id_or_slug)
            task = self.repos.scheduled_tasks.get_one(uuid_val)
            if not task:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Scheduled task '{id_or_slug}' not found",
                )
            self.repos.scheduled_tasks.delete(uuid_val)
        except ValueError:
            # Try slug
            task = self.repos.scheduled_tasks.get_by_slug(id_or_slug)
            if not task:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Scheduled task '{id_or_slug}' not found",
                ) from None
            self.repos.scheduled_tasks.delete(task.id)

        # Emit event
        self.event_bus.dispatch(
            integration_id="platform_api",
            group_id=self.group_id,
            event_type=EventTypes.scheduled_task_deleted,
            document_data=EventScheduledTaskData.from_model(task, workspace_name=self.group.name if self.group else None),
            message=f"Scheduled task '{task.name}' deleted",
            entity_id=task.id,
            entity_type="scheduled_task",
        )

    @router.post("/{id_or_slug}/execute", status_code=status.HTTP_202_ACCEPTED)
    def execute_task(self, id_or_slug: Annotated[str, Path()]):
        """Manually trigger task execution."""
        require_workspace_admin(self.user, self.group_id)
        # Try UUID first
        try:
            uuid_val = UUID4(id_or_slug)
            task = self.repos.scheduled_tasks.get_one(uuid_val)
        except ValueError:
            # Try slug
            task = self.repos.scheduled_tasks.get_by_slug(id_or_slug)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scheduled task '{id_or_slug}' not found",
            )

        # Emit triggered event immediately
        self.event_bus.dispatch(
            integration_id="platform_api",
            group_id=self.group_id,
            event_type=EventTypes.scheduled_task_triggered,
            document_data=EventScheduledTaskData.from_model(task, workspace_name=self.group.name if self.group else None),
            message=f"Scheduled task '{task.name}' manually triggered",
            entity_id=task.id,
            entity_type="scheduled_task",
        )

        return {"message": f"Task '{task.name}' execution triggered"}

    @router.get("/{id_or_slug}/history", response_model=list[ScheduledTaskExecutionLogRead])
    def get_task_history(self, id_or_slug: Annotated[str, Path()], limit: int = 50):
        """Get execution history for a task."""
        require_workspace_admin(self.user, self.group_id)
        # Try UUID first
        try:
            uuid_val = UUID4(id_or_slug)
            task = self.repos.scheduled_tasks.get_one(uuid_val)
        except ValueError:
            # Try slug
            task = self.repos.scheduled_tasks.get_by_slug(id_or_slug)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scheduled task '{id_or_slug}' not found",
            )

        return self.repos.scheduled_task_executions.get_task_history(task.id, limit=limit)
