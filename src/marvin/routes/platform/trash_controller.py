"""The workspace's Trash as a whole: entries, assets and resources (services/trash.py).

Trashed entries are listed by the Trash system collection; trashed assets and resources here. Moving
something to the Trash, restoring it or deleting one item forever stays on its own routes (DELETE,
POST /{id}/restore, DELETE ?permanent=true); emptying the whole Trash is here, ADMIN/OWNER only.
"""

from fastapi import APIRouter, Query, Response

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin
from marvin.routes._base.paging import paged
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
    def trashed_assets(
        self,
        response: Response,
        limit: int | None = Query(None, ge=1, description="At most this many (default: all of them)"),
        offset: int = Query(0, ge=0, description="Skip this many first (with `limit`, one page)"),
    ) -> list[AssetRead]:
        """The assets in the Trash (Ask files too), by name (Z first, as always). `limit`/`offset` page it; `X-Total-Count` says how many in
        all. The library's `GET /assets?trashed=true` lists them with its filters and orders."""
        from marvin.db.models.platform import Assets

        return [AssetRead.model_validate(a) for a in self._trashed(Assets, response, limit, offset)]

    @router.get("/resources", response_model=list[ResourceRead], summary="List Trashed Resources")
    def trashed_resources(
        self,
        response: Response,
        limit: int | None = Query(None, ge=1, description="At most this many (default: all of them)"),
        offset: int = Query(0, ge=0, description="Skip this many first (with `limit`, one page)"),
    ) -> list[ResourceRead]:
        """The resources in the Trash, by name (Z first, as always). `limit`/`offset` page it; `X-Total-Count` says how many in all."""
        from marvin.db.models.platform.resources import Resources

        return [ResourceRead.model_validate(r) for r in self._trashed(Resources, response, limit, offset)]

    def _trashed(self, model, response: Response, limit: int | None, offset: int) -> list:
        """The workspace's trashed rows of ``model`` (assets or resources), by name Z to A, one page of them, tags loaded up front."""
        from sqlalchemy.orm import selectinload

        query = self.session.query(model).filter(model.group_id == self.group_id, model.trashed_at.isnot(None))
        return paged(query.order_by(model.name.desc(), model.id.desc()), response, limit, offset).options(selectinload(model.tags)).all()

    @router.post("/empty", summary="Empty the Trash")
    def empty(self) -> dict:
        """Delete everything in the Trash forever — entries, assets (their files too) and resources (ADMIN/OWNER).
        Each goes through its normal delete, so `entry_deleted` / `asset_deleted` / `resource_deleted` fire.
        Returns `{deleted: total, entries, assets, resources}`."""
        require_workspace_admin(self.user, self.group_id)
        n = trash.empty_all(self.session, self.group_id, actor_id=self.user.id, event_bus=self.event_bus)
        return {"status": "ok", "deleted": n["total"], "entries": n["entries"], "assets": n["assets"], "resources": n["resources"]}
