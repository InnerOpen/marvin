"""
Platform endpoints for managing workspace members.

Provides workspace member management for regular users (not admin):
- Listing workspace members
- Adding users to workspaces
- Updating member roles
- Removing members from workspaces

Requires workspace ADMIN/OWNER role for most operations.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import UUID4

from marvin.core.dependencies import require_workspace_admin, require_workspace_member
from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.schemas.user.user import PrivateUser, WorkspaceMembershipRead
from marvin.schemas.workspace import WorkspaceMemberCreate, WorkspaceMemberUpdate
from marvin.services.event_bus_service.event_types import EventMemberData, EventOperation, EventTypes

router = APIRouter(prefix="/workspaces/{workspace_id}/members")


@controller(router)
class WorkspaceMembersController(BaseUserController):
    """Controller for workspace member management endpoints."""

    @router.get("", response_model=list[WorkspaceMembershipRead], summary="List Workspace Members")
    def list_workspace_members(
        self,
        workspace_id: UUID4,
        _user: PrivateUser = Depends(require_workspace_admin()),
    ) -> list[WorkspaceMembershipRead]:
        """
        List all members of a workspace.

        Requires workspace ADMIN or OWNER role.

        Args:
            workspace_id: The workspace to query
            _user: Authenticated user with admin permissions (injected by dependency)

        Returns:
            List of workspace memberships with user details
        """
        return self.repos.workspace_members.get_members_by_workspace(workspace_id)

    @router.post("", response_model=WorkspaceMembershipRead, status_code=status.HTTP_201_CREATED, summary="Add Workspace Member")
    def add_workspace_member(
        self,
        workspace_id: UUID4,
        data: WorkspaceMemberCreate,
        current_user: PrivateUser = Depends(require_workspace_admin()),
    ) -> WorkspaceMembershipRead:
        """
        Add a user to a workspace with a specific role.

        Requires workspace ADMIN or OWNER role.

        Args:
            workspace_id: The workspace to add the user to
            data: User ID and role to assign
            current_user: Authenticated user with admin permissions

        Raises:
            HTTPException: 404 if user or workspace not found
            HTTPException: 409 if user is already a member (unique constraint violation)

        Returns:
            The created workspace membership
        """
        # Verify user exists
        user = self.repos.users.get_one(data.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with ID {data.user_id} not found.")

        # Verify workspace exists
        workspace = self.repos.groups.get_one(workspace_id)
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workspace with ID {workspace_id} not found.")

        # Check if user is already a member
        existing = self.repos.workspace_members.get_membership(data.user_id, workspace_id)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"User {user.username} is already a member of this workspace.")

        # Add the member
        result = self.repos.workspace_members.add_member(user_id=data.user_id, workspace_id=workspace_id, role=data.workspace_role)
        self.session.commit()

        # Emit event
        self.event_bus.dispatch(
            integration_id="workspace_management",
            group_id=workspace_id,
            event_type=EventTypes.member_added,
            user_id=current_user.id,  # who did it; the member is the subject
            entity_id=data.user_id,
            entity_type="member",
            document_data=EventMemberData(
                operation=EventOperation.create,
                workspace_id=workspace_id,
                workspace_name=workspace.name,
                user_id=data.user_id,
                username=user.username,
                user_full_name=user.full_name if user else None,
                role=data.workspace_role.value,
            ),
            message=f"User {user.username} added to workspace with role {data.workspace_role.value}",
        )

        return result

    @router.get("/{user_id}", response_model=WorkspaceMembershipRead, summary="Get Workspace Member")
    def get_workspace_member(
        self,
        workspace_id: UUID4,
        user_id: UUID4,
        _user: PrivateUser = Depends(require_workspace_member()),
    ) -> WorkspaceMembershipRead:
        """
        Get details of a specific workspace member.

        Any workspace member can view other members.

        Args:
            workspace_id: The workspace
            user_id: The user to look up
            _user: Authenticated workspace member (any role)

        Raises:
            HTTPException: 404 if membership not found

        Returns:
            The workspace membership details
        """
        membership = self.repos.workspace_members.get_membership(user_id, workspace_id)
        if not membership:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} is not a member of workspace {workspace_id}.")

        return membership

    @router.put("/{user_id}", response_model=WorkspaceMembershipRead, summary="Update Member Role")
    def update_workspace_member_role(
        self,
        workspace_id: UUID4,
        user_id: UUID4,
        data: WorkspaceMemberUpdate,
        current_user: PrivateUser = Depends(require_workspace_admin()),
    ) -> WorkspaceMembershipRead:
        """
        Update a workspace member's role.

        Requires workspace ADMIN or OWNER role.

        Validations:
        - Cannot change your own role (prevents self-lockout)
        - Cannot demote the last OWNER (prevents workspace lockout)

        Args:
            workspace_id: The workspace
            user_id: The user whose role to update
            data: The new role to assign
            current_user: Authenticated admin user

        Raises:
            HTTPException: 404 if membership not found
            HTTPException: 403 if trying to change own role
            HTTPException: 403 if trying to demote the last OWNER

        Returns:
            The updated membership
        """
        # Verify membership exists
        membership = self.repos.workspace_members.get_membership(user_id, workspace_id)
        if not membership:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} is not a member of workspace {workspace_id}.")

        # Prevent changing your own role (self-lockout protection)
        if user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="You cannot change your own role. Ask another admin to update your permissions."
            )

        # If demoting an OWNER, check that there's at least one other OWNER
        if membership.workspace_role == WorkspaceRole.OWNER and data.workspace_role != WorkspaceRole.OWNER:
            owner_count = self.repos.workspace_members.count_workspace_owners(workspace_id)
            if owner_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Cannot demote the last OWNER. Promote another member to OWNER first."
                )

        # Update the role
        updated = self.repos.workspace_members.update_role(user_id=user_id, workspace_id=workspace_id, new_role=data.workspace_role)

        if not updated:
            # This shouldn't happen since we checked above, but handle defensively
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found.")

        self.session.commit()

        workspace_obj = self.repos.groups.get_one(workspace_id)
        updated_username = updated.user.username if updated.user else str(user_id)
        # Emit event
        self.event_bus.dispatch(
            integration_id="workspace_management",
            group_id=workspace_id,
            event_type=EventTypes.member_role_changed,
            user_id=current_user.id,  # who did it; the member is the subject
            entity_id=user_id,
            entity_type="member",
            document_data=EventMemberData(
                operation=EventOperation.update,
                workspace_id=workspace_id,
                workspace_name=workspace_obj.name if workspace_obj else None,
                user_id=user_id,
                username=updated_username,
                user_full_name=updated.user.full_name if updated.user else None,
                role=data.workspace_role.value,
                previous_role=membership.workspace_role.value,
            ),
            message=f"User {updated_username} role changed from {membership.workspace_role.value} to {data.workspace_role.value}",
        )

        return updated

    @router.delete("/{user_id}", summary="Remove Workspace Member")
    def remove_workspace_member(
        self,
        workspace_id: UUID4,
        user_id: UUID4,
        current_user: PrivateUser = Depends(require_workspace_admin()),
    ) -> dict:
        """
        Remove a user from a workspace.

        Requires workspace ADMIN or OWNER role.

        Validations:
        - Cannot remove yourself (use "leave workspace" endpoint instead)
        - Cannot remove the last OWNER (prevents workspace lockout)

        Args:
            workspace_id: The workspace
            user_id: The user to remove
            current_user: Authenticated admin user

        Raises:
            HTTPException: 404 if membership not found
            HTTPException: 403 if trying to remove yourself
            HTTPException: 403 if trying to remove the last OWNER
        """
        # Verify membership exists
        membership = self.repos.workspace_members.get_membership(user_id, workspace_id)
        if not membership:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} is not a member of workspace {workspace_id}.")

        # Prevent removing yourself (self-lockout protection)
        if user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot remove yourself from the workspace. Use the 'leave workspace' endpoint instead.",
            )

        # If removing an OWNER, check that there's at least one other OWNER
        if membership.workspace_role == WorkspaceRole.OWNER:
            owner_count = self.repos.workspace_members.count_workspace_owners(workspace_id)
            if owner_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Cannot remove the last OWNER. Promote another member to OWNER first."
                )

        workspace_obj = self.repos.groups.get_one(workspace_id)
        removed_username = membership.user.username if membership.user else str(user_id)
        # Emit event before removal
        self.event_bus.dispatch(
            integration_id="workspace_management",
            group_id=workspace_id,
            event_type=EventTypes.member_removed,
            user_id=current_user.id,  # who did it; the member is the subject
            entity_id=user_id,
            entity_type="member",
            document_data=EventMemberData(
                operation=EventOperation.delete,
                workspace_id=workspace_id,
                workspace_name=workspace_obj.name if workspace_obj else None,
                user_id=user_id,
                username=removed_username,
                user_full_name=membership.user.full_name if membership.user else None,
                role=membership.workspace_role.value,
            ),
            message=f"User {removed_username} removed from workspace",
        )

        # Remove the member
        removed = self.repos.workspace_members.remove_member(user_id, workspace_id)

        if not removed:
            # This shouldn't happen since we checked above, but handle defensively
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found.")

        self.session.commit()
        return {"status": "ok", "message": "Workspace member removed successfully"}
