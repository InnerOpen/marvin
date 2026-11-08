"""
Views API.

A package can bring views: plain data describing a way of looking at an entry, e.g. a story as a timeline (see
`services/blueprints/views.py`). They are read-only here and open to anyone in the workspace, because a view only reads entries and assets
through their own APIs, which check who may see what. Installing and removing them is the package's business (`/groups/packages`).
"""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import BaseUserController, controller
from marvin.schemas.platform.views import ViewRead, ViewSummary
from marvin.services.blueprints import packages as service

router = APIRouter(prefix="/groups/views")


@controller(router)
class ViewsController(BaseUserController):
    """The views the active workspace's packages bring."""

    @router.get("", response_model=list[ViewSummary])
    def list_views(self, entry_type: str | None = None):
        """Every view installed here, by name; `entry_type` keeps only the views of that type."""
        return service.list_views(self.session, self.group_id, entry_type)

    @router.get("/{slug}", response_model=ViewRead)
    def get_view(self, slug: str):
        """One view with its definition."""
        found = service.get_view(self.session, self.group_id, slug)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such view in this workspace")
        return found
