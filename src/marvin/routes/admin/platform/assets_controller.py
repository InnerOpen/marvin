"""Admin assets controller."""

from functools import cached_property

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.repos.platform import AssetsRepository
from marvin.routes._base import BaseAdminController, controller
from marvin.routes._base.mixins import HttpRepo
from marvin.schemas.platform import AssetCreate, AssetRead
from marvin.services import trash

router = APIRouter(prefix="/assets")


@controller(router)
class AdminAssetsRoutes(BaseAdminController):
    """Controller for managing assets."""

    @cached_property
    def repo(self) -> AssetsRepository:
        """Get assets repository for current group."""
        if not self.user or not self.user.group_id:
            raise ValueError("User must have a group assigned")
        return AssetsRepository(self.session, self.user.group_id)

    @property
    def mixins(self) -> HttpRepo[AssetCreate, AssetRead, AssetCreate]:
        """Mixin for CRUD operations."""
        return HttpRepo[AssetCreate, AssetRead, AssetCreate](self.repo, self.logger, self.registered_exceptions)

    @router.get("", response_model=list[AssetRead], summary="List Assets")
    def get_all(self) -> list[AssetRead]:
        """Get all assets in the user's group."""
        assets = [x for x in self.repo.get_all() if x.trashed_at is None]  # not those in the Trash
        return [self.repo.schema.from_orm(a) for a in assets]

    @router.post("", response_model=AssetRead, summary="Create Asset")
    def create(self, schema: AssetCreate) -> AssetRead:
        """Create a new asset."""
        return self.mixins.create_one(schema)

    @router.get("/{asset_id}", response_model=AssetRead, summary="Get Asset")
    def get_one(self, asset_id: UUID4) -> AssetRead:
        """Get a specific asset."""
        return self.mixins.get_one(asset_id)

    @router.delete("/{asset_id}", response_model=AssetRead, summary="Move Asset to Trash (or delete a trashed asset forever)")
    def delete(self, asset_id: UUID4, permanent: bool = False) -> AssetRead:
        """Move the asset to the Trash, as the workspace route does; with `permanent=true`, delete one already in the
        Trash forever (its file too). Returns the asset as it was."""
        current = self.mixins.get_one(asset_id)
        group_id = self.user.group_id
        if not permanent:
            trash.trash(self.session, group_id, trash.ASSET, asset_id, actor_id=self.user.id, event_bus=self.event_bus)
            return self.mixins.get_one(asset_id)
        if current.trashed_at is None:
            detail = "Only an asset in the Trash can be deleted forever. Move it to the Trash first."
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
        trash.delete_forever(self.session, group_id, trash.ASSET, [asset_id], actor_id=self.user.id, event_bus=self.event_bus)
        return current

    @router.post("/{asset_id}/restore", response_model=AssetRead, summary="Restore Asset from Trash")
    def restore(self, asset_id: UUID4) -> AssetRead:
        """Take the asset out of the Trash."""
        self.mixins.get_one(asset_id)  # 404 when missing
        trash.restore(self.session, self.user.group_id, trash.ASSET, asset_id, actor_id=self.user.id, event_bus=self.event_bus)
        return self.mixins.get_one(asset_id)
