"""Admin resources controller."""

from functools import cached_property

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.repos.platform import ResourcesRepository
from marvin.routes._base import BaseAdminController, controller
from marvin.routes._base.mixins import HttpRepo
from marvin.schemas.platform import ResourceCreate, ResourceRead, ResourceUpdate
from marvin.services import trash

router = APIRouter(prefix="/resources")


@controller(router)
class AdminResourcesRoutes(BaseAdminController):
    """Controller for managing resources."""

    @cached_property
    def repo(self) -> ResourcesRepository:
        """Get resources repository for current group."""
        if not self.user or not self.user.group_id:
            raise ValueError("User must have a group assigned")
        return ResourcesRepository(self.session, self.user.group_id)

    @property
    def mixins(self) -> HttpRepo[ResourceCreate, ResourceRead, ResourceUpdate]:
        """Mixin for CRUD operations."""
        return HttpRepo[ResourceCreate, ResourceRead, ResourceUpdate](self.repo, self.logger, self.registered_exceptions)

    @router.get("", response_model=list[ResourceRead], summary="List Resources")
    def get_all(self) -> list[ResourceRead]:
        """Get all resources in the user's group."""
        resources = [x for x in self.repo.get_all() if x.trashed_at is None]  # not those in the Trash
        return [self.repo.schema.from_orm(r) for r in resources]

    @router.post("", response_model=ResourceRead, summary="Create Resource")
    def create(self, schema: ResourceCreate) -> ResourceRead:
        """Create a new resource."""
        return self.mixins.create_one(schema)

    @router.get("/{resource_id}", response_model=ResourceRead, summary="Get Resource")
    def get_one(self, resource_id: UUID4) -> ResourceRead:
        """Get a specific resource."""
        return self.mixins.get_one(resource_id)

    @router.put("/{resource_id}", response_model=ResourceRead, summary="Update Resource")
    def update(self, resource_id: UUID4, schema: ResourceUpdate) -> ResourceRead:
        """Update a resource."""
        return self.mixins.update_one(resource_id, schema)

    @router.delete("/{resource_id}", response_model=ResourceRead, summary="Move Resource to Trash (or delete a trashed resource forever)")
    def delete(self, resource_id: UUID4, permanent: bool = False) -> ResourceRead:
        """Move the resource to the Trash, as the workspace route does; with `permanent=true`, delete one already in the
        Trash forever. Returns the resource as it was."""
        current = self.mixins.get_one(resource_id)
        group_id = self.user.group_id
        if not permanent:
            trash.trash(self.session, group_id, trash.RESOURCE, resource_id, actor_id=self.user.id, event_bus=self.event_bus)
            return self.mixins.get_one(resource_id)
        if current.trashed_at is None:
            detail = "Only a resource in the Trash can be deleted forever. Move it to the Trash first."
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
        trash.delete_forever(self.session, group_id, trash.RESOURCE, [resource_id], actor_id=self.user.id, event_bus=self.event_bus)
        return current

    @router.post("/{resource_id}/restore", response_model=ResourceRead, summary="Restore Resource from Trash")
    def restore(self, resource_id: UUID4) -> ResourceRead:
        """Take the resource out of the Trash."""
        self.mixins.get_one(resource_id)  # 404 when missing
        trash.restore(self.session, self.user.group_id, trash.RESOURCE, resource_id, actor_id=self.user.id, event_bus=self.event_bus)
        return self.mixins.get_one(resource_id)
