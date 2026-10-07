"""The workspace's Trash as a whole: entries, assets and resources (services/trash.py).

Trashed entries are listed by the Trash system collection; trashed assets and resources here. Moving
something to the Trash, restoring it or deleting one item forever stays on its own routes (DELETE,
POST /{id}/restore, DELETE ?permanent=true); emptying the whole Trash is here, ADMIN/OWNER only.
"""

from fastapi import APIRouter

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin
from marvin.schemas.platform import AssetRead, ResourceRead
from marvin.services import trash
from marvin.services.entries import trash as entry_trash

router = APIRouter(prefix="/trash")


@controller(router)
class TrashController(BaseUserController):
    @router.get("", summary="Trash summary")
    def summary(self) -> dict:
        """How many entries, assets and resources are in the Trash (`total` beside them) and how long it keeps
        them (`effective_days`, 0 = until emptied; the platform default and this workspace's override beside it)."""
        return {**trash.counts(self.session, self.group_id), **entry_trash.auto_empty_status(self.session, self.group_id)}

    @router.get("/assets", response_model=list[AssetRead], summary="List Trashed Assets")
    def trashed_assets(self) -> list[AssetRead]:
        return [a for a in self.repos.assets.get_all(order_by="name") if a.trashed_at is not None]

    @router.get("/resources", response_model=list[ResourceRead], summary="List Trashed Resources")
    def trashed_resources(self) -> list[ResourceRead]:
        return [r for r in self.repos.resources.get_all(order_by="name") if r.trashed_at is not None]

    @router.post("/empty", summary="Empty the Trash")
    def empty(self) -> dict:
        """Delete everything in the Trash forever — entries, assets (their files too) and resources (ADMIN/OWNER).
        Each goes through its normal delete, so `entry_deleted` / `asset_deleted` / `resource_deleted` fire.
        Returns `{deleted: total, entries, assets, resources}`."""
        require_workspace_admin(self.user, self.group_id)
        n = trash.empty_all(self.session, self.group_id, actor_id=self.user.id, event_bus=self.event_bus)
        return {"status": "ok", "deleted": n["total"], "entries": n["entries"], "assets": n["assets"], "resources": n["resources"]}
