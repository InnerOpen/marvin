"""Resource routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_editor
from marvin.schemas.platform import ResourceCreate, ResourceRead, ResourceUpdate
from marvin.services import trash
from marvin.services.event_bus_service.event_types import EventOperation, EventResourceData, EventTypes

router = APIRouter(prefix="/resources")


@controller(router)
class ResourcesController(BaseUserController):
    """Authenticated CRUD routes for resources. Any member reads; creating, editing, deleting and
    accepting AI suggestions on a resource is EDITOR and above.

    Delete moves a resource to the Trash (services/trash.py): it leaves the list, and fetching it by id
    shows its `trashed_at`. Only a trashed resource can be deleted forever."""

    @router.get("", response_model=list[ResourceRead], summary="List Resources")
    def list_resources(self) -> list[ResourceRead]:
        """Every resource but those in the Trash."""
        return [r for r in self.repos.resources.get_all(order_by="name") if r.trashed_at is None]

    @router.post("", response_model=ResourceRead, status_code=status.HTTP_201_CREATED, summary="Create Resource")
    def create_resource(self, data: ResourceCreate) -> ResourceRead:
        require_workspace_editor(self.user, self.group_id)
        # Inject created_by and group_id from authenticated user
        data_dict = data.model_dump()
        data_dict["created_by"] = self.user.id
        data_dict["group_id"] = self.group_id
        resource = self.repos.resources.create(data_dict)

        # Emit event
        self.event_bus.dispatch(
            integration_id="resource_management",
            group_id=self.group_id,
            event_type=EventTypes.resource_created,
            document_data=EventResourceData(
                operation=EventOperation.create,
                resource_id=resource.id,
                resource_name=resource.name,
                resource_slug=resource.slug,
                resource_type=resource.resource_type,
                workspace_id=self.group_id,
                workspace_name=self.group.name if self.group else None,
                url=resource.url,
            ),
            message=f"Resource '{resource.name}' created",
        )

        return resource

    @router.get("/{item_id}", response_model=ResourceRead, summary="Get Resource")
    def get_resource(self, item_id: UUID4) -> ResourceRead:
        resource = self.repos.resources.get_one(item_id)
        if not resource:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
        return resource

    @router.patch("/{item_id}", response_model=ResourceRead, summary="Update Resource")
    def update_resource(self, item_id: UUID4, data: ResourceUpdate) -> ResourceRead:
        require_workspace_editor(self.user, self.group_id)
        current = self.repos.resources.get_one(item_id)
        if not current:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
        if current.trashed_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This resource is in the Trash. Restore it before editing it.")

        resource = self.repos.resources.update(item_id, data)

        # Emit event
        self.event_bus.dispatch(
            integration_id="resource_management",
            group_id=self.group_id,
            event_type=EventTypes.resource_updated,
            document_data=EventResourceData(
                operation=EventOperation.update,
                resource_id=resource.id,
                resource_name=resource.name,
                resource_slug=resource.slug,
                resource_type=resource.resource_type,
                workspace_id=self.group_id,
                workspace_name=self.group.name if self.group else None,
                url=resource.url,
            ),
            message=f"Resource '{resource.name}' updated",
        )

        return resource

    @router.post("/{item_id}/apply-suggestion", response_model=ResourceRead, summary="Apply AI Suggestion")
    def apply_suggestion(self, item_id: UUID4) -> ResourceRead:
        """Apply the resource's staged AI suggestion (suggestion_json) and clear it."""
        require_workspace_editor(self.user, self.group_id)
        if not self.repos.resources.get_one(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
        return self.repos.resources.apply_suggestion(item_id)

    @router.post("/{item_id}/reject-suggestion", response_model=ResourceRead, summary="Reject AI Suggestion")
    def reject_suggestion(self, item_id: UUID4) -> ResourceRead:
        """Discard the resource's staged AI suggestion without applying it."""
        require_workspace_editor(self.user, self.group_id)
        if not self.repos.resources.get_one(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
        return self.repos.resources.clear_suggestion(item_id)

    @router.delete("/{item_id}", summary="Move Resource to Trash (or delete a trashed resource forever)")
    def delete_resource(self, item_id: UUID4, permanent: bool = False) -> dict:
        """Move the resource to the Trash (`resource_trashed`). With `permanent=true`, delete a resource
        already in the Trash forever (`resource_deleted`); any other resource gets a 409."""
        require_workspace_editor(self.user, self.group_id)
        resource = self.repos.resources.get_one(item_id)
        if not resource:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
        if permanent:
            if resource.trashed_at is None:
                detail = "Only a resource in the Trash can be deleted forever. Move it to the Trash first."
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
            if not trash.delete_forever(self.session, self.group_id, trash.RESOURCE, [item_id], actor_id=self.user.id, event_bus=self.event_bus):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
            return {"status": "ok", "message": "Resource deleted forever", "deleted": True}
        trash.trash(self.session, self.group_id, trash.RESOURCE, item_id, actor_id=self.user.id, event_bus=self.event_bus)
        return {"status": "ok", "message": "Resource moved to the Trash", "trashed": True}

    @router.post("/{item_id}/restore", response_model=ResourceRead, summary="Restore Resource from Trash")
    def restore_resource(self, item_id: UUID4) -> ResourceRead:
        """Take a resource out of the Trash (`resource_restored`)."""
        require_workspace_editor(self.user, self.group_id)
        resource = self.repos.resources.get_one(item_id)
        if not resource:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
        if resource.trashed_at is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This resource is not in the Trash.")
        trash.restore(self.session, self.group_id, trash.RESOURCE, item_id, actor_id=self.user.id, event_bus=self.event_bus)
        return self.repos.resources.get_one(item_id)
