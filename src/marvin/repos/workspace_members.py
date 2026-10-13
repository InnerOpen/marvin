"""
Repository for workspace member operations.

Provides methods for managing workspace memberships including:
- Adding/removing users from workspaces
- Updating user roles within workspaces
- Querying workspace members
"""

from pydantic import UUID4
from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload

from marvin.db.models.users.roles import WorkspaceRole
from marvin.db.models.users.workspace_members import WorkspaceMembers as WorkspaceMembersModel
from marvin.schemas.user.user import WorkspaceMembershipRead

from .repository_generic import RepositoryGeneric


class RepositoryWorkspaceMembers(RepositoryGeneric[WorkspaceMembershipRead, WorkspaceMembersModel]):
    """
    Repository for managing workspace member relationships.

    Note: This repository is NOT group-scoped because it manages memberships
    across all workspaces. Individual methods will handle workspace-specific
    filtering via workspace_id parameters.
    """

    def get_members_by_workspace(self, workspace_id: UUID4) -> list[WorkspaceMembershipRead]:
        """
        Get all members of a specific workspace.

        Args:
            workspace_id: The workspace (group) ID to query

        Returns:
            List of workspace memberships with user details
        """
        stmt = (
            select(WorkspaceMembersModel)
            .where(WorkspaceMembersModel.group_id == workspace_id)
            .options(joinedload(WorkspaceMembersModel.user))
            .order_by(WorkspaceMembersModel.workspace_role, WorkspaceMembersModel.created_at)
        )

        results = self.session.execute(stmt).scalars().all()
        return [WorkspaceMembershipRead.model_validate(member) for member in results]

    def get_user_workspaces(self, user_id: UUID4) -> list[WorkspaceMembershipRead]:
        """
        Get all workspaces a user belongs to.

        Args:
            user_id: The user ID to query

        Returns:
            List of workspace memberships for the user
        """
        stmt = (
            select(WorkspaceMembersModel)
            .where(WorkspaceMembersModel.user_id == user_id)
            .options(joinedload(WorkspaceMembersModel.workspace))
            .order_by(WorkspaceMembersModel.created_at)
        )

        results = self.session.execute(stmt).scalars().all()
        return [WorkspaceMembershipRead.model_validate(member) for member in results]

    def get_membership(self, user_id: UUID4, workspace_id: UUID4) -> WorkspaceMembershipRead | None:
        """
        Get a specific user's membership in a workspace.

        Args:
            user_id: The user ID
            workspace_id: The workspace (group) ID

        Returns:
            The workspace membership if it exists, None otherwise
        """
        stmt = (
            select(WorkspaceMembersModel)
            .where(WorkspaceMembersModel.user_id == user_id, WorkspaceMembersModel.group_id == workspace_id)
            .options(joinedload(WorkspaceMembersModel.user))
        )

        result = self.session.execute(stmt).scalar_one_or_none()
        return WorkspaceMembershipRead.model_validate(result) if result else None

    def add_member(self, user_id: UUID4, workspace_id: UUID4, role: WorkspaceRole) -> WorkspaceMembershipRead:
        """
        Add a user to a workspace with a specific role.

        Args:
            user_id: The user to add
            workspace_id: The workspace (group) to add them to
            role: The role to assign (OWNER, ADMIN, EDITOR, AUTHOR, VIEWER)

        Returns:
            The created workspace membership

        Raises:
            IntegrityError: If the user is already a member (unique constraint)
        """
        member = WorkspaceMembersModel(session=self.session, user_id=user_id, group_id=workspace_id, workspace_role=role)

        self.session.add(member)
        self.session.flush()
        self.session.refresh(member)

        return WorkspaceMembershipRead.model_validate(member)

    def update_role(self, user_id: UUID4, workspace_id: UUID4, new_role: WorkspaceRole) -> WorkspaceMembershipRead | None:
        """
        Update a user's role in a workspace.

        Args:
            user_id: The user whose role to update
            workspace_id: The workspace (group) they're in
            new_role: The new role to assign

        Returns:
            The updated membership, or None if membership doesn't exist
        """
        stmt = select(WorkspaceMembersModel).where(WorkspaceMembersModel.user_id == user_id, WorkspaceMembersModel.group_id == workspace_id)

        member = self.session.execute(stmt).scalar_one_or_none()
        if not member:
            return None

        member.workspace_role = new_role
        self.session.flush()
        self.session.refresh(member)

        return WorkspaceMembershipRead.model_validate(member)

    def remove_member(self, user_id: UUID4, workspace_id: UUID4) -> bool:
        """
        Remove a user from a workspace.

        Args:
            user_id: The user to remove
            workspace_id: The workspace (group) to remove them from

        Returns:
            True if a membership was deleted, False if it didn't exist
        """
        stmt = delete(WorkspaceMembersModel).where(WorkspaceMembersModel.user_id == user_id, WorkspaceMembersModel.group_id == workspace_id)

        result = self.session.execute(stmt)
        self.session.flush()

        return result.rowcount > 0

    def count_workspace_owners(self, workspace_id: UUID4) -> int:
        """
        Count how many OWNER-role members a workspace has.

        Used to prevent removing the last owner (which would lock out the workspace).

        Args:
            workspace_id: The workspace to check

        Returns:
            Number of members with OWNER role
        """
        stmt = select(WorkspaceMembersModel).where(
            WorkspaceMembersModel.group_id == workspace_id, WorkspaceMembersModel.workspace_role == WorkspaceRole.OWNER
        )

        result = self.session.execute(stmt).scalars().all()
        return len(result)

    def user_is_member(self, user_id: UUID4, group_id: UUID4) -> bool:
        """
        Check if a user is a member of a workspace.

        Args:
            user_id: The user ID to check
            group_id: The workspace (group) ID to check

        Returns:
            True if user is a member, False otherwise
        """
        stmt = select(WorkspaceMembersModel).where(WorkspaceMembersModel.user_id == user_id, WorkspaceMembersModel.group_id == group_id)

        result = self.session.execute(stmt).scalar_one_or_none()
        return result is not None

    def get_user_memberships(self, user_id: UUID4) -> list[WorkspaceMembersModel]:
        """
        Get all workspace memberships for a user (returns models, not schemas).

        Args:
            user_id: The user ID

        Returns:
            List of WorkspaceMembers model instances
        """
        stmt = (
            select(WorkspaceMembersModel)
            .where(WorkspaceMembersModel.user_id == user_id)
            .options(joinedload(WorkspaceMembersModel.workspace))
            .order_by(WorkspaceMembersModel.created_at)
        )

        return list(self.session.execute(stmt).scalars().all())
