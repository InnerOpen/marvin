"""Entry type routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.core.root_logger import get_logger
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin
from marvin.schemas.platform import EntryTypeCreate, EntryTypeRead, EntryTypeUpdate
from marvin.services.event_bus_service.event_types import EventEntryTypeData, EventOperation, EventTypes

logger = get_logger(__name__)

router = APIRouter(prefix="/entry-types")


@controller(router)
class EntryTypesController(BaseUserController):
    """Authenticated CRUD routes for entry types. Any member reads; changing an entry type changes the
    workspace's content schema, so creating, editing and deleting one is workspace-admin only."""

    @router.get("", response_model=list[EntryTypeRead], summary="List Entry Types")
    def list_entry_types(self) -> list[EntryTypeRead]:
        return self.repos.entry_types.get_all(order_by="sort_order", order_descending=False)

    @router.post("", response_model=EntryTypeRead, status_code=status.HTTP_201_CREATED, summary="Create Entry Type")
    def create_entry_type(self, data: EntryTypeCreate) -> EntryTypeRead:
        require_workspace_admin(self.user, self.group_id)
        entry_type = self.repos.entry_types.create(data)

        # Emit event
        self.event_bus.dispatch(
            integration_id="entry_type_management",
            group_id=self.group_id,
            event_type=EventTypes.entry_type_created,
            document_data=EventEntryTypeData(
                operation=EventOperation.create,
                entry_type_id=entry_type.id,
                entry_type_name=entry_type.name,
                entry_type_slug=entry_type.slug,
                workspace_id=entry_type.group_id,
                workspace_name=self.group.name if self.group else None,
                description=entry_type.description,
            ),
            message=f"Entry type '{entry_type.name}' created",
        )

        return entry_type

    @router.get("/{item_id}", response_model=EntryTypeRead, summary="Get Entry Type")
    def get_entry_type(self, item_id: UUID4) -> EntryTypeRead:
        entry_type = self.repos.entry_types.get_one(item_id)
        if not entry_type:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry type not found.")
        return entry_type

    @router.patch("/{item_id}", response_model=EntryTypeRead, summary="Update Entry Type")
    def update_entry_type(self, item_id: UUID4, data: EntryTypeUpdate) -> EntryTypeRead:
        require_workspace_admin(self.user, self.group_id)
        if not self.repos.entry_types.get_one(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry type not found.")

        entry_type = self.repos.entry_types.update(item_id, data)

        # Emit event
        self.event_bus.dispatch(
            integration_id="entry_type_management",
            group_id=self.group_id,
            event_type=EventTypes.entry_type_updated,
            document_data=EventEntryTypeData(
                operation=EventOperation.update,
                entry_type_id=entry_type.id,
                entry_type_name=entry_type.name,
                entry_type_slug=entry_type.slug,
                workspace_id=entry_type.group_id,
                workspace_name=self.group.name if self.group else None,
                description=entry_type.description,
            ),
            message=f"Entry type '{entry_type.name}' updated",
        )

        return entry_type

    @router.delete("/{item_id}", summary="Delete Entry Type")
    def delete_entry_type(self, item_id: UUID4) -> dict:
        require_workspace_admin(self.user, self.group_id)
        entry_type = self.repos.entry_types.get_one(item_id)
        if not entry_type:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry type not found.")

        # Emit event before deletion
        self.event_bus.dispatch(
            integration_id="entry_type_management",
            group_id=self.group_id,
            event_type=EventTypes.entry_type_deleted,
            document_data=EventEntryTypeData(
                operation=EventOperation.delete,
                entry_type_id=entry_type.id,
                entry_type_name=entry_type.name,
                entry_type_slug=entry_type.slug,
                workspace_id=entry_type.group_id,
                workspace_name=self.group.name if self.group else None,
                description=entry_type.description,
            ),
            message=f"Entry type '{entry_type.name}' deleted",
        )

        self.repos.entry_types.delete(item_id)
        return {"status": "ok", "message": "Entry type deleted successfully"}
