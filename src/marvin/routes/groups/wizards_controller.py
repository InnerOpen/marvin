"""
Guided setups (wizards) API.

A package can bring wizards: plain data describing a multi-page setup (see `services/blueprints/wizards.py`). They are read-only here and
open to anyone in the workspace, because a wizard only reads and writes through the entries and assets APIs, which check who may do what.
Installing and removing them is the package's business (`/groups/packages`, owners and admins).
"""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import BaseUserController, controller
from marvin.schemas.platform.wizards import WizardRead, WizardSummary
from marvin.services.blueprints import packages as service

router = APIRouter(prefix="/groups/wizards")


@controller(router)
class WizardsController(BaseUserController):
    """The guided setups the active workspace's packages bring."""

    @router.get("", response_model=list[WizardSummary])
    def list_wizards(self, entry_type: str | None = None):
        """Every wizard installed here, by name. `entry_type` keeps only those that put a button on that type's entries."""
        return service.list_wizards(self.session, self.group_id, entry_type)

    @router.get("/{slug}", response_model=WizardRead)
    def get_wizard(self, slug: str):
        """One wizard with its steps."""
        found = service.get_wizard(self.session, self.group_id, slug)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such wizard in this workspace")
        return found
