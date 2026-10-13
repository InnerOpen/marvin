"""
Authorization roles for Marvin platform and workspaces.

This module defines the role-based authorization model that replaces
scattered boolean permission flags.
"""

import enum


class PlatformRole(enum.Enum):
    """
    Platform-level roles for Marvin.

    A user has ONE platform role that determines their platform-level access.
    Platform roles are independent of workspace membership.
    """

    NONE = "NONE"
    """No platform-level privileges. Standard user."""

    SUPER_ADMIN = "SUPER_ADMIN"
    """
    Platform administrator with unrestricted access.

    Super admins can:
    - View every workspace (not limited by group_id)
    - Create/delete workspaces
    - Manage workspace settings for any workspace
    - Manage users across the platform
    - Access all publishing configurations
    - Perform platform-level operations

    This role should be reserved for the platform owner/operators only.
    """


class WorkspaceRole(enum.Enum):
    """
    Workspace-level roles for workspace members.

    Each user-workspace membership has ONE workspace role that determines
    what they can do within that specific workspace.
    """

    OWNER = "OWNER"
    """
    Workspace owner with full control.

    Owners can:
    - Everything an ADMIN can do
    - Transfer ownership (future)
    - Delete the workspace (future)

    There should typically be one OWNER per workspace.
    """

    ADMIN = "ADMIN"
    """
    Workspace administrator.

    Admins can:
    - Manage workspace settings
    - Manage workspace members (invite/remove)
    - Manage entry types and collections
    - Create/edit/delete all entries
    - Manage assets
    - Configure publishing (API clients, site settings)
    """

    EDITOR = "EDITOR"
    """
    Content editor.

    Editors can:
    - Create entries
    - Edit all entries (not just their own)
    - Upload and manage assets
    - Organize content into collections

    Editors CANNOT:
    - Manage workspace settings
    - Invite/remove users
    - Configure publishing
    """

    AUTHOR = "AUTHOR"
    """
    Content author.

    Authors can:
    - Create entries (owned by them)
    - Edit their own entries
    - Upload assets

    Authors CANNOT:
    - Edit others' entries
    - Manage workspace settings
    - Invite users
    """

    VIEWER = "VIEWER"
    """
    Read-only viewer.

    Viewers can:
    - View published content
    - View workspace content they have access to

    Viewers CANNOT:
    - Create or edit content
    - Manage anything

    Note: For true read-only external access, use API clients instead.
    """


# Helper functions for role checks


def workspace_role_can_manage_settings(role: WorkspaceRole) -> bool:
    """Check if workspace role can manage workspace settings."""
    return role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)


def workspace_role_can_manage_members(role: WorkspaceRole) -> bool:
    """Check if workspace role can invite/remove workspace members."""
    return role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)


def workspace_role_can_edit_all_entries(role: WorkspaceRole) -> bool:
    """Check if workspace role can edit all entries (not just own)."""
    return role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EDITOR)


def workspace_role_can_create_entries(role: WorkspaceRole) -> bool:
    """Check if workspace role can create entries."""
    return role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR)


def workspace_role_can_manage_publishing(role: WorkspaceRole) -> bool:
    """Check if workspace role can manage API clients and publishing settings."""
    return role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)


# Role hierarchy (for future use)
WORKSPACE_ROLE_HIERARCHY = {
    WorkspaceRole.OWNER: 5,
    WorkspaceRole.ADMIN: 4,
    WorkspaceRole.EDITOR: 3,
    WorkspaceRole.AUTHOR: 2,
    WorkspaceRole.VIEWER: 1,
}


def workspace_role_has_higher_or_equal_privilege(role: WorkspaceRole, compared_to: WorkspaceRole) -> bool:
    """
    Check if one workspace role has higher or equal privilege than another.

    Useful for permission checks like "can user A edit user B's content".
    """
    return WORKSPACE_ROLE_HIERARCHY.get(role, 0) >= WORKSPACE_ROLE_HIERARCHY.get(compared_to, 0)
