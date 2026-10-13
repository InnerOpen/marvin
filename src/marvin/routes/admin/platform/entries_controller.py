"""Admin entries controller."""

from functools import cached_property

from fastapi import APIRouter
from pydantic import UUID4

from marvin.repos.platform import EntriesRepository
from marvin.routes._base import BaseAdminController, controller
from marvin.routes._base.mixins import HttpRepo
from marvin.schemas.platform import EntryCreate, EntryRead, EntryUpdate

router = APIRouter(prefix="/entries")


@controller(router)
class AdminEntriesRoutes(BaseAdminController):
    """Controller for managing entries."""

    @cached_property
    def repo(self) -> EntriesRepository:
        """Get entries repository for current group."""
        if not self.user or not self.user.group_id:
            raise ValueError("User must have a group assigned")
        return EntriesRepository(self.session, self.user.group_id)

    @property
    def mixins(self) -> HttpRepo[EntryCreate, EntryRead, EntryUpdate]:
        """Mixin for CRUD operations."""
        return HttpRepo[EntryCreate, EntryRead, EntryUpdate](self.repo, self.logger, self.registered_exceptions)

    @router.get("", response_model=list[EntryRead], summary="List Entries")
    def get_all(self) -> list[EntryRead]:
        """Get all entries in the user's group."""
        entries = self.repo.get_all()
        return [self.repo.schema.from_orm(e) for e in entries]

    @router.post("", response_model=EntryRead, summary="Create Entry")
    def create(self, schema: EntryCreate) -> EntryRead:
        """Create a new entry."""
        return self.mixins.create_one(schema)

    @router.get("/{entry_id}", response_model=EntryRead, summary="Get Entry")
    def get_one(self, entry_id: UUID4) -> EntryRead:
        """Get a specific entry."""
        return self.mixins.get_one(entry_id)

    @router.put("/{entry_id}", response_model=EntryRead, summary="Update Entry")
    def update(self, entry_id: UUID4, schema: EntryUpdate) -> EntryRead:
        """Update an entry."""
        return self.mixins.update_one(entry_id, schema)

    @router.delete("/{entry_id}", response_model=EntryRead, summary="Delete Entry")
    def delete(self, entry_id: UUID4) -> EntryRead:
        """Delete an entry."""
        return self.mixins.delete_one(entry_id)
