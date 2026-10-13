"""Admin collections controller."""

from functools import cached_property

from fastapi import APIRouter
from pydantic import UUID4

from marvin.repos.platform import CollectionsRepository
from marvin.routes._base import BaseAdminController, controller
from marvin.routes._base.mixins import HttpRepo
from marvin.schemas.platform import CollectionCreate, CollectionRead, CollectionUpdate

router = APIRouter(prefix="/collections")


@controller(router)
class AdminCollectionsRoutes(BaseAdminController):
    """Controller for managing collections."""

    @cached_property
    def repo(self) -> CollectionsRepository:
        """Get collections repository for current group."""
        if not self.user or not self.user.group_id:
            raise ValueError("User must have a group assigned")
        return CollectionsRepository(self.session, self.user.group_id)

    @property
    def mixins(self) -> HttpRepo[CollectionCreate, CollectionRead, CollectionUpdate]:
        """Mixin for CRUD operations."""
        return HttpRepo[CollectionCreate, CollectionRead, CollectionUpdate](self.repo, self.logger, self.registered_exceptions)

    @router.get("", response_model=list[CollectionRead], summary="List Collections")
    def get_all(self) -> list[CollectionRead]:
        """Get all collections in the user's group."""
        collections = self.repo.get_all()
        return [self.repo.schema.from_orm(c) for c in collections]

    @router.post("", response_model=CollectionRead, summary="Create Collection")
    def create(self, schema: CollectionCreate) -> CollectionRead:
        """Create a new collection."""
        return self.mixins.create_one(schema)

    @router.get("/{collection_id}", response_model=CollectionRead, summary="Get Collection")
    def get_one(self, collection_id: UUID4) -> CollectionRead:
        """Get a specific collection."""
        return self.mixins.get_one(collection_id)

    @router.put("/{collection_id}", response_model=CollectionRead, summary="Update Collection")
    def update(self, collection_id: UUID4, schema: CollectionUpdate) -> CollectionRead:
        """Update a collection."""
        return self.mixins.update_one(collection_id, schema)

    @router.delete("/{collection_id}", response_model=CollectionRead, summary="Delete Collection")
    def delete(self, collection_id: UUID4) -> CollectionRead:
        """Delete a collection."""
        return self.mixins.delete_one(collection_id)
