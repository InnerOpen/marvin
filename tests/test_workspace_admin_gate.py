"""The shared gate for workspace-management routes (workflows, incoming webhooks, AI providers/models,
MCP servers). Five copies compared the role's string value with a number — `"ADMIN" >= 4` — so every
workspace admin who wasn't also a platform admin got a 500 instead of the page."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.routes._base.checks import require_workspace_admin

GROUP = uuid.uuid4()


def _user(role=None, *, admin=False, platform_role=PlatformRole.NONE):
    return SimpleNamespace(admin=admin, platform_role=platform_role, get_workspace_role=lambda gid: role if gid == GROUP else None)


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
def test_workspace_owner_or_admin_passes(role):
    require_workspace_admin(_user(role), GROUP)  # used to raise TypeError


@pytest.mark.parametrize("role", [WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER, None])
def test_below_admin_or_non_member_is_403(role):
    with pytest.raises(HTTPException) as exc:
        require_workspace_admin(_user(role), GROUP)
    assert exc.value.status_code == 403


def test_platform_super_admin_passes_without_membership():
    require_workspace_admin(_user(platform_role=PlatformRole.SUPER_ADMIN), GROUP)


def test_legacy_admin_flag_still_passes():
    require_workspace_admin(_user(admin=True), GROUP)


def test_the_five_controllers_use_the_shared_gate():
    from marvin.routes.ai import mcp_servers_controller, models_controller, providers_controller
    from marvin.routes.automations import automations_controller
    from marvin.routes.hooks import incoming_webhooks_controller

    for module in (providers_controller, models_controller, mcp_servers_controller, automations_controller, incoming_webhooks_controller):
        assert module._require_admin is require_workspace_admin, module.__name__
