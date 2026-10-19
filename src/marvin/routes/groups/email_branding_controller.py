"""Workspace email branding API: the name, footer line and accent colour on the workspace's emails, each falling back
when blank (services/email/branding.py). Workspace-admin only."""

from fastapi import APIRouter, HTTPException, status

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin
from marvin.schemas.group.email_branding import WorkspaceEmailBrandingRead, WorkspaceEmailBrandingUpdate
from marvin.services.email.branding import save_workspace_branding, workspace_branding_view
from marvin.services.platform_policy import PolicyError

router = APIRouter(prefix="/groups/email-branding")


@controller(router)
class EmailBrandingController(BaseUserController):
    @router.get("", response_model=WorkspaceEmailBrandingRead, summary="Workspace email branding")
    def get_branding(self) -> WorkspaceEmailBrandingRead:
        require_workspace_admin(self.user, self.group_id)
        return WorkspaceEmailBrandingRead(**workspace_branding_view(self.session, self.group_id))

    @router.put("", response_model=WorkspaceEmailBrandingRead, summary="Set the workspace email branding")
    def put_branding(self, data: WorkspaceEmailBrandingUpdate) -> WorkspaceEmailBrandingRead:
        require_workspace_admin(self.user, self.group_id)
        try:
            view = save_workspace_branding(self.session, self.group_id, data.model_dump())
        except PolicyError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        return WorkspaceEmailBrandingRead(**view)
