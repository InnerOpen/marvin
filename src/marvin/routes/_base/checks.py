"""
This module provides the `OperationChecks` class, designed to centralize
permission checking logic based on user attributes.

It is intended to be instantiated with a user object and then used within
route controllers or services to verify if the user has the necessary
permissions to perform certain operations. If a check fails, it raises
an appropriate FastAPI HTTPException.
"""

from fastapi import HTTPException, status  # For standard HTTP exceptions
from pydantic import UUID4

from marvin.db.models.users.roles import (
    PlatformRole,
    WorkspaceRole,
    workspace_role_can_manage_members,
    workspace_role_has_higher_or_equal_privilege,
)
from marvin.schemas.user import PrivateUser  # Pydantic schema for user data


class OperationChecks:
    """
    A utility class for performing common permission checks based on user attributes.

    This class is typically instantiated with a `PrivateUser` object. Its methods
    then check specific boolean permission flags on that user (e.g., `can_manage`,
    `can_invite`). If a permission is not granted, an `HTTPException` (usually
    403 Forbidden) is raised.

    This helps keep permission logic consistent and centralized, making route
    handlers cleaner.
    """

    user: PrivateUser
    """The user object whose permissions are being checked."""

    # Pre-defined HTTP exceptions for common authentication/authorization errors.
    ForbiddenException = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="User does not have sufficient permissions for this operation.",  # Added more specific default detail
    )
    """HTTPException raised when a permission check fails (403 Forbidden)."""

    UnauthorizedException = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User is not authenticated.",  # Added more specific default detail
    )
    """HTTPException for cases where authentication is required but missing (401 Unauthorized)."""

    def __init__(self, user: PrivateUser) -> None:
        """
        Initializes the OperationChecks instance with a user.

        Args:
            user (PrivateUser): The authenticated user whose permissions will be checked.
        """
        self.user = user

    # =========================================
    # Workspace Role Checks
    # =========================================

    def can_manage_members(self, group_id: UUID4, granting: WorkspaceRole | None = None) -> bool:
        """
        Workspace OWNERs and ADMINs (and platform super admins) may invite and remove members.

        Args:
            group_id: The workspace being managed.
            granting: The role an invitation would grant. Nobody but a super admin may grant a
                      role above their own, so an ADMIN cannot mint OWNER invitations.

        Raises:
            HTTPException (403 Forbidden): If the user may not manage members of this workspace.
        """
        if self.user.platform_role == PlatformRole.SUPER_ADMIN:
            return True
        role = self.user.get_workspace_role(group_id)
        if role is None or not workspace_role_can_manage_members(role):
            raise self.ForbiddenException
        if granting is not None and not workspace_role_has_higher_or_equal_privilege(role, granting):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You cannot invite someone as {granting.value}; your role is {role.value}.",
            )
        return True

    # =========================================
    # User Permission Checks
    # =========================================

    def can_manage(self) -> bool:
        """
        Checks if the user has 'manage' permissions.

        Raises:
            HTTPException (403 Forbidden): If `user.can_manage` is False.

        Returns:
            bool: True if the user has 'manage' permissions.
        """
        if not self.user.can_manage:
            # User does not have the 'can_manage' permission, raise ForbiddenException.
            raise self.ForbiddenException
        return True

    def can_invite(self) -> bool:
        """
        Checks if the user has 'invite' permissions.

        Raises:
            HTTPException (403 Forbidden): If `user.admin` or `user.can_invite` is False.

        Returns:
            bool: True if the user has 'invite' permissions.
        """
        if not self.user.can_invite:
            # User does not have the 'can_invite' permission, raise ForbiddenException.
            raise self.ForbiddenException
        return True

    def can_organize(self) -> bool:
        """
        Checks if the user has 'organize' permissions.

        Note: The `can_organize` attribute was noted in `marvin.db.models.users.users.Users._set_permissions`
        as a parameter but not a mapped database column. This check assumes `user.can_organize`
        is a valid attribute on the `PrivateUser` schema, potentially set based on other logic.

        Raises:
            HTTPException (403 Forbidden): If `user.can_organize` is False.

        Returns:
            bool: True if the user has 'organize' permissions.
        """
        if not hasattr(self.user, "can_organize") or not self.user.can_organize:  # Added hasattr check for safety
            # User does not have the 'can_organize' permission, or attribute is missing.
            raise self.ForbiddenException
        return True
