"""
"Delete all of these" on an Automation page's *From a removed integration* section (``/groups/removed-integration-items``).

``DELETE /{kind}`` deletes this workspace's items of that kind that an integration installed and that integration no longer
exists (rule and one safety guard: services/automation/removed_integration.py). ADMIN and above; the role is checked first.
"""

from fastapi import APIRouter

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin
from marvin.schemas.group.removed_integration import RemovedIntegrationDeleted, RemovedKind
from marvin.services.automation import removed_integration as removed

router = APIRouter(prefix="/groups/removed-integration-items")


@controller(router)
class RemovedIntegrationController(BaseUserController):
    @router.delete("/{kind}", response_model=RemovedIntegrationDeleted, summary="Delete a kind's items left by a removed integration")
    def delete_removed_items(self, kind: RemovedKind) -> RemovedIntegrationDeleted:
        require_workspace_admin(self.user, self.group_id)
        outcome = removed.delete_removed(self.session, self.group_id, kind)
        return RemovedIntegrationDeleted(kind=kind, deleted=len(outcome.names), names=outcome.names, skipped=outcome.skipped)
