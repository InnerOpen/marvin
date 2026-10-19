"""A fake signed-in user that is in one workspace, as `services.workspace.current.current_workspace_id` reads it.

Tests that stand in for `get_current_user` with a `SimpleNamespace` give it `group_id` / `active_group_id` and spread
this in: the resolver needs the user's platform role and their role in a workspace (a home they are not a member of
is no workspace).
"""

from types import SimpleNamespace

from marvin.db.models.users.roles import PlatformRole, WorkspaceRole


def member_of(gid, role: WorkspaceRole | None = WorkspaceRole.EDITOR, platform_role: PlatformRole = PlatformRole.NONE) -> dict:
    return {
        "platform_role": platform_role,
        "workspace_memberships": [SimpleNamespace(group_id=gid, workspace_role=role)] if role else [],
        "get_workspace_role": lambda group_id: role if str(group_id) == str(gid) else None,
    }
