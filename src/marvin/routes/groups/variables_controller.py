"""Workspace Variables API — plain-text key-value config referenced via {{SLUG}}."""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.db.models.groups.variables import WorkspaceVariable
from marvin.routes._base import BaseUserController, controller
from marvin.schemas.group.variable import (
    WorkspaceVariableCreate,
    WorkspaceVariableRead,
    WorkspaceVariableUpdate,
)
from marvin.services.event_bus_service.event_types import EventOperation, EventTypes, EventVariableData

router = APIRouter(prefix="/groups/variables")


def _get_var_or_404(session, var_id: UUID4, group_id: UUID4) -> WorkspaceVariable:
    var = session.get(WorkspaceVariable, var_id)
    if not var or var.group_id != group_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variable not found.")
    return var


@controller(router)
class VariablesController(BaseUserController):
    """Workspace variable CRUD."""

    def _emit(self, event_type: EventTypes, operation: EventOperation, *, slug: str, name: str | None, value: str | None, var_id: UUID4) -> None:
        """Dispatch a variable_* event. Variables are plain-text, so the value may travel."""
        self.event_bus.dispatch(
            integration_id="variable_management",
            group_id=self.group_id,
            event_type=event_type,
            document_data=EventVariableData(
                operation=operation,
                slug=slug,
                name=name,
                value=value,
                workspace_id=self.group_id,
                workspace_name=self.group.name if self.group else None,
            ),
            message=f"Variable {slug} {operation.value}d",
            user_id=self.user.id if self.user else None,
            entity_id=var_id,
            entity_type="variable",
        )

    @router.get("", response_model=list[WorkspaceVariableRead])
    def list_variables(self):
        """List all variables (including values — variables are not secret)."""
        return self.repos.workspace_variables().get_all(order_by="name")

    @router.post("", response_model=WorkspaceVariableRead, status_code=status.HTTP_201_CREATED)
    def create_variable(self, data: WorkspaceVariableCreate):
        """Create a workspace variable."""
        existing = self.repos.workspace_variables().get_all()
        if any(v.slug == data.slug for v in existing):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Variable slug '{data.slug}' already exists in this workspace.",
            )

        var = WorkspaceVariable(
            session=self.session,
            group_id=self.group_id,
            name=data.name,
            slug=data.slug,
            description=data.description,
            value=data.value,
        )
        self.session.add(var)
        self.session.commit()
        self.session.refresh(var)
        self._emit(EventTypes.variable_created, EventOperation.create, slug=var.slug, name=var.name, value=var.value, var_id=var.id)
        return WorkspaceVariableRead.model_validate(var)

    @router.patch("/{var_id}", response_model=WorkspaceVariableRead)
    def update_variable(self, var_id: UUID4, data: WorkspaceVariableUpdate):
        """Update a variable's name, description, or value."""
        var = _get_var_or_404(self.session, var_id, self.group_id)
        if data.name is not None:
            var.name = data.name
        if data.description is not None:
            var.description = data.description
        if data.value is not None:
            var.value = data.value
        self.session.commit()
        self.session.refresh(var)
        self._emit(EventTypes.variable_updated, EventOperation.update, slug=var.slug, name=var.name, value=var.value, var_id=var.id)
        return WorkspaceVariableRead.model_validate(var)

    @router.delete("/{var_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_variable(self, var_id: UUID4):
        """Delete a variable."""
        var = self.session.get(WorkspaceVariable, var_id)
        if not var or var.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variable not found.")
        slug, name = var.slug, var.name
        self.session.delete(var)
        self.session.commit()
        self._emit(EventTypes.variable_deleted, EventOperation.delete, slug=slug, name=name, value=None, var_id=var_id)
