"""API routes for per-workspace AI workflow policy settings."""

from fastapi import APIRouter, HTTPException, status

from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.controller import controller
from marvin.schemas.group.ai_settings import (
    WorkspaceAISettingsRead,
    WorkspaceAISettingsUpdate,
)

router = APIRouter(prefix="/groups/ai-settings", route_class=MarvinCrudRoute)


@controller(router)
class AISettingsController(BaseUserController):
    """Manage per-workspace AI workflow policy — group_id comes from the user session."""

    def _require_admin(self) -> None:
        if self.user.admin:
            return
        for m in self.user.workspace_memberships:
            if m.group_id == self.group_id and WORKSPACE_ROLE_HIERARCHY.get(m.workspace_role, 0) >= 4:
                return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ADMIN or OWNER role required.")

    def _allow_workspace_credentials(self) -> bool:
        from marvin.core.config import get_app_settings

        return bool(getattr(get_app_settings(), "AI_ALLOW_WORKSPACE_CREDENTIALS", True))

    @router.get("/sources", summary="List invocation sources (for the policy editor)")
    def list_invocation_sources(self) -> list[dict]:
        """The catalog of AI invocation surfaces — key + human label/description — so the settings UI
        can render a toggle per source. A source is allowed unless the workspace policy sets it false."""
        from marvin.services.ai.operations.base import INVOCATION_SOURCE_CATALOG

        return [dict(s) for s in INVOCATION_SOURCE_CATALOG]

    @router.get("", response_model=WorkspaceAISettingsRead, summary="Get AI Workflow Settings")
    def get_ai_settings(self) -> WorkspaceAISettingsRead:
        """Return current settings; returns defaults when no row exists yet."""
        allow_ws = self._allow_workspace_credentials()
        row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if not row:
            return WorkspaceAISettingsRead(group_id=self.group_id, allow_workspace_credentials=allow_ws)
        result = WorkspaceAISettingsRead.model_validate(row)
        result.allow_workspace_credentials = allow_ws
        return result

    @router.patch("", response_model=WorkspaceAISettingsRead, summary="Update AI Workflow Settings")
    def update_ai_settings(self, data: WorkspaceAISettingsUpdate) -> WorkspaceAISettingsRead:
        """Upsert AI workflow settings. Creates the row on first write."""
        self._require_admin()

        # Platform policy: workspaces may be barred from using their own AI credentials.
        if data.credential_mode == "workspace" and not self._allow_workspace_credentials():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace-provided AI credentials are disabled by the platform administrator.",
            )

        warnings = []
        if data.credential_mode == "workspace" and data.secret_ref:
            from marvin.db.models.groups.secrets import WorkspaceSecret

            exists = self.session.query(WorkspaceSecret).filter_by(group_id=self.group_id, slug=data.secret_ref).first()
            if not exists:
                warnings.append(f"Secret slug '{data.secret_ref}' not found in this workspace.")

        if "approval_mode" in data.model_fields_set:
            from marvin.services.ai.approval import APPROVAL_MODES

            if data.approval_mode not in APPROVAL_MODES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"approval_mode must be one of: {', '.join(APPROVAL_MODES)}.",
                )

        row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        if not row:
            row = WorkspaceAISettingsModel(session=self.session, group_id=self.group_id)
            self.session.add(row)

        for field, value in data.model_dump(exclude_unset=True).items():
            if hasattr(row, field):
                setattr(row, field, value)

        if data.credential_mode is not None and data.credential_mode != "workspace":
            row.secret_ref = None

        self.session.commit()
        self.session.refresh(row)

        result = WorkspaceAISettingsRead.model_validate(row)
        if warnings:
            self.logger.warning("AI settings saved with warnings: %s", "; ".join(warnings))
        return result
