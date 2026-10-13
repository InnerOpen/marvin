"""
Controller for workspace activation - allows users to switch between workspaces.

Endpoints:
- GET /self/workspaces/current - Get current active workspace
- PUT /self/workspaces/current - Set active workspace
- GET /self/workspaces - List all accessible workspaces
"""

from fastapi import APIRouter, HTTPException, status

from marvin.db.models.users.roles import PlatformRole
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.controller import controller
from marvin.schemas.group.group import GroupRead
from marvin.schemas.workspace.workspace_activation import (
    WorkspaceActivationRequest,
    WorkspaceWithMembership,
)

router = APIRouter(prefix="/self/workspaces", tags=["User: Self Service"])


@controller(router)
class WorkspaceActivationController(BaseUserController):
    """Controller for workspace activation operations."""

    @router.get("/current", response_model=GroupRead)
    def get_current_workspace(self) -> GroupRead:
        """
        Get the user's currently active workspace.

        Returns:
            The active workspace details.
        """
        workspace_id = self.user.active_group_id or self.user.group_id
        workspace = self.repos.groups.get_one(workspace_id)

        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace {workspace_id} not found",
            )

        return workspace

    @router.put("/current", response_model=GroupRead)
    def set_active_workspace(self, request: WorkspaceActivationRequest) -> GroupRead:
        """
        Set the user's active workspace.

        Regular users can only activate workspaces they're members of.
        SUPER_ADMIN users can activate any workspace.

        Args:
            request: The workspace activation request (accepts slug or UUID).

        Returns:
            The newly activated workspace.

        Raises:
            HTTPException: 403 if user is not a member of the workspace (non-SUPER_ADMIN).
            HTTPException: 404 if workspace doesn't exist.
        """
        # Verify workspace exists (accepts slug or UUID)
        workspace = self.repos.groups.get_by_slug_or_id(request.workspace)
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace '{request.workspace}' not found",
            )

        # Check membership (SUPER_ADMIN can access any workspace)
        if self.user.platform_role != PlatformRole.SUPER_ADMIN:
            is_member = self.repos.workspace_members.user_is_member(
                user_id=self.user.id,
                group_id=workspace.id,
            )
            if not is_member:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not a member of this workspace",
                )

        # Update user's active workspace
        from sqlalchemy import select

        from marvin.db.models.users.users import Users

        user_model = self.repos.session.execute(select(Users).where(Users.id == self.user.id)).scalar_one_or_none()

        if not user_model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        user_model.active_group_id = workspace.id
        self.repos.session.commit()

        # Dispatch workspace.activated event
        from marvin.services.event_bus_service.event_types import EventTypes

        self.event_bus.dispatch(
            integration_id="workspace_activation",
            group_id=workspace.id,
            event_type=EventTypes.workspace_activated,
            document_data=None,
            message=f"User '{self.user.username}' activated workspace '{workspace.name}'",
            user_id=self.user.id,
            entity_id=workspace.id,
            entity_type="workspace",
        )

        return workspace

    @router.get("", response_model=list[WorkspaceWithMembership])
    def list_accessible_workspaces(self) -> list[WorkspaceWithMembership]:
        """
        List all workspaces accessible to the current user.

        For SUPER_ADMIN: Returns all workspaces in the system.
        For regular users: Returns only workspaces they're members of.

        Returns:
            List of workspaces with membership details.
        """
        # The platform workspace comes first whatever it is named, then the rest by name (_platform_first).
        current_workspace_id = self.user.active_group_id or self.user.group_id

        # SUPER_ADMIN sees all workspaces
        if self.user.platform_role == PlatformRole.SUPER_ADMIN:
            from marvin.db.models.users.roles import WorkspaceRole

            all_workspaces = self.repos.groups.get_all_models()
            return _platform_first(
                [
                    WorkspaceWithMembership(
                        workspace=GroupRead.model_validate(ws),
                        role=self.user.get_workspace_role(ws.id) or WorkspaceRole.OWNER,
                        is_active=(ws.id == current_workspace_id),
                    )
                    for ws in all_workspaces
                ]
            )

        # Regular users see only their memberships
        memberships = self.repos.workspace_members.get_user_memberships(self.user.id)

        result = []
        for membership in memberships:
            workspace = self.repos.groups.get_one(membership.group_id)
            if workspace:
                result.append(
                    WorkspaceWithMembership(
                        workspace=workspace,
                        role=membership.workspace_role,
                        is_active=(workspace.id == current_workspace_id),
                    )
                )

        return _platform_first(result)


def _platform_first(workspaces: list[WorkspaceWithMembership]) -> list[WorkspaceWithMembership]:
    """The switcher's order: the platform workspace on top (it can be renamed, so not by name), then by name."""
    return sorted(workspaces, key=lambda w: (not w.workspace.is_platform, w.workspace.name.casefold()))
