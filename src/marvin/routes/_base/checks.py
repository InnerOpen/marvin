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
    workspace_role_can_create_entries,
    workspace_role_can_edit_all_entries,
    workspace_role_can_manage_members,
    workspace_role_can_manage_settings,
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

    def can_manage_settings(self, group_id: UUID4) -> bool:
        """Workspace OWNERs and ADMINs (and platform super admins) may change workspace structure —
        entry types, collections, tasks, webhooks, workflows.

        Raises:
            HTTPException (403 Forbidden): If the user may not manage this workspace's settings.
        """
        if self.user.platform_role == PlatformRole.SUPER_ADMIN:
            return True
        role = self.user.get_workspace_role(group_id)
        if role is None or not workspace_role_can_manage_settings(role):
            raise self.ForbiddenException
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


def require_workspace_admin(user: PrivateUser, group_id: UUID4) -> None:
    """Raise 403 unless the user is a workspace OWNER/ADMIN, a platform super admin, or a legacy
    `admin`. The shared gate for workspace-management routes (workflows, webhooks, AI providers…).

    Five controllers used to carry their own copy that compared the role's *string* value with a
    number (`"ADMIN" >= 4`), which raised TypeError — a 500 for every workspace admin who wasn't
    also a platform admin.
    """
    if getattr(user, "admin", False) or user.platform_role == PlatformRole.SUPER_ADMIN:
        return
    role = user.get_workspace_role(group_id)
    if role is None or not workspace_role_can_manage_settings(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ADMIN or OWNER role required.")


def _bypasses_workspace_roles(user: PrivateUser) -> bool:
    """Platform super admins and legacy `admin` users pass every workspace role gate."""
    return bool(getattr(user, "admin", False)) or user.platform_role == PlatformRole.SUPER_ADMIN


def require_workspace_role(user: PrivateUser, group_id: UUID4, minimum: WorkspaceRole) -> None:
    """Raise 403 unless the user holds `minimum` or a higher role in the workspace (or bypasses roles).

    The content routes' gate: EDITOR for content writes, AUTHOR where an author may act on their own
    work, ADMIN for structure (`require_workspace_admin`). Call it before looking anything up, so a
    member below the gate gets a 403, not a 404 that confirms an id exists.
    """
    if _bypasses_workspace_roles(user):
        return
    role = user.get_workspace_role(group_id)
    if role is None or not workspace_role_has_higher_or_equal_privilege(role, minimum):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"{minimum.value} role or higher required.")


def require_workspace_editor(user: PrivateUser, group_id: UUID4) -> None:
    """Raise 403 unless the user is an EDITOR or above: the gate for writing workspace content."""
    require_workspace_role(user, group_id, WorkspaceRole.EDITOR)


AUTHOR_LOCKED_STATUSES = frozenset({"approved", "published"})
"""Entry statuses only an EDITOR or above may set, or edit an entry in: approving and publishing is an
editor's call, so an AUTHOR can't publish their own entry or change it once it is approved or live."""


def _author_may_set(new_status: str | None, publish_at) -> bool:
    return new_status not in AUTHOR_LOCKED_STATUSES and publish_at is None


def require_can_create_entry(user: PrivateUser, group_id: UUID4, new_status: str | None = None, publish_at=None) -> None:
    """Raise 403 unless the user may create this entry.

    AUTHORs create entries (owned by them) but not approved or published ones, and can't schedule a
    publish (`publish_at`); EDITORs and above create anything.
    """
    if _bypasses_workspace_roles(user):
        return
    role = user.get_workspace_role(group_id)
    if role is None or not workspace_role_can_create_entries(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AUTHOR role or higher required.")
    if not workspace_role_can_edit_all_entries(role) and not _author_may_set(new_status, publish_at):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only an EDITOR or above can approve, publish or schedule an entry.")


def require_can_edit_entry(user: PrivateUser, group_id: UUID4, entry, new_status: str | None = None, publish_at=None) -> None:
    """Raise 403 unless the user may change (or delete) `entry`.

    EDITORs and above edit every entry. An AUTHOR edits only entries they created, only while those
    are not approved or published, and can't approve, publish or schedule them. Call
    `require_workspace_role(..., WorkspaceRole.AUTHOR)` before looking the entry up, then this.
    """
    if _bypasses_workspace_roles(user):
        return
    role = user.get_workspace_role(group_id)
    if role is not None and workspace_role_can_edit_all_entries(role):
        return
    if role is None or not workspace_role_can_create_entries(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AUTHOR role or higher required.")
    if str(getattr(entry, "created_by", None)) != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="An AUTHOR can only change their own entries.")
    if getattr(entry, "status", None) in AUTHOR_LOCKED_STATUSES or not _author_may_set(new_status, publish_at):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an EDITOR or above can approve, publish or schedule an entry, or change one that is.",
        )


def editable_entry(user: PrivateUser, group_id: UUID4, repos, entry_id: UUID4, new_status: str | None = None, publish_at=None):
    """Load an entry the caller is about to change, or raise.

    403 below AUTHOR (before the lookup, so a VIEWER learns nothing about ids); 404 if the entry isn't
    in this workspace (`repos` is workspace-scoped, which also scopes junction deletes keyed by the
    entry id); then `require_can_edit_entry` (an AUTHOR: own entries, not approved/published).
    """
    require_workspace_role(user, group_id, WorkspaceRole.AUTHOR)
    entry = repos.entries.get_one(entry_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
    require_can_edit_entry(user, group_id, entry, new_status, publish_at)
    return entry
