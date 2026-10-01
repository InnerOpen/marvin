"""Workspace member roles: invitations, the invite permission, and a platform admin's user edit.

Regressions from 2026-10-01: a user invited as ADMIN joined as EDITOR (the form never sent the
role), inviting was gated on the legacy per-user `can_invite` flag instead of the workspace role,
and saving the admin's Edit user form always failed because the update schema demanded a password.
"""

import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pytest import fixture

from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.repos.all_repositories import get_repositories
from marvin.routes._base.checks import OperationChecks
from marvin.schemas.user import UserAdminUpdate

GROUP_ID = uuid.uuid4()


def _checks(platform_role=PlatformRole.NONE, workspace_role=None) -> OperationChecks:
    """OperationChecks over a user stub: only the two attributes the role check reads."""
    user = SimpleNamespace(
        platform_role=platform_role,
        get_workspace_role=lambda group_id: workspace_role if group_id == GROUP_ID else None,
    )
    return OperationChecks(user)  # type: ignore[arg-type]


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
def test_can_manage_members_with_owner_or_admin_role_allows(role):
    assert _checks(workspace_role=role).can_manage_members(GROUP_ID)


@pytest.mark.parametrize("role", [WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER, None])
def test_can_manage_members_below_admin_or_non_member_is_forbidden(role):
    with pytest.raises(HTTPException) as exc:
        _checks(workspace_role=role).can_manage_members(GROUP_ID)
    assert exc.value.status_code == 403


def test_can_manage_members_admin_granting_owner_is_forbidden():
    with pytest.raises(HTTPException) as exc:
        _checks(workspace_role=WorkspaceRole.ADMIN).can_manage_members(GROUP_ID, granting=WorkspaceRole.OWNER)
    assert exc.value.status_code == 403


def test_can_manage_members_super_admin_outside_workspace_allows():
    checks = _checks(platform_role=PlatformRole.SUPER_ADMIN)
    assert checks.can_manage_members(GROUP_ID, granting=WorkspaceRole.OWNER)


def test_user_admin_update_ignores_password_and_unsent_fields():
    data = UserAdminUpdate.model_validate({"fullName": "Grace", "password": "plaintext"})
    assert data.model_dump(exclude_unset=True) == {"full_name": "Grace"}


@fixture
def workspace(db_session):
    """A throwaway workspace plus one existing user (can_invite on, so a reset would show)."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"roles-{marker}", slug=f"roles-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"u-{marker}",
            email=f"u-{marker}@t.test",
            full_name="Before",
            password="not-a-real-hash",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
            can_invite=True,
        )
    )
    db_session.commit()
    yield SimpleNamespace(id=gid, name=group.name, marker=marker, user_id=uid)

    from marvin.db.models.groups.invite_tokens import GroupInviteToken
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    db_session.rollback()
    db_session.query(WorkspaceMembers).filter(WorkspaceMembers.group_id == gid).delete()
    db_session.query(GroupInviteToken).filter(GroupInviteToken.group_id == gid).delete()
    db_session.query(Users).filter(Users.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_partial_admin_update_changes_only_sent_fields(db_session, workspace):
    repos = get_repositories(db_session, group_id=None)

    updated = repos.users.update(workspace.user_id, UserAdminUpdate(full_name="After"))

    assert updated.full_name == "After"
    assert updated.can_invite is True


def test_invitation_role_is_applied_on_registration(db_session, workspace):
    from marvin.db.models.users.workspace_members import WorkspaceMembers
    from marvin.schemas.group.invite_token import InviteTokenSave
    from marvin.schemas.user.registration import UserRegistrationCreate
    from marvin.services.user.registration_service import RegistrationService

    repos = get_repositories(db_session, group_id=None)
    token = f"tok-{workspace.marker}"
    repos.group_invite_tokens.create(
        InviteTokenSave(uses_left=1, workspace_role=WorkspaceRole.ADMIN, group_id=workspace.id, token=token)
    )

    user = RegistrationService(logging.getLogger("test"), repos).register_user(
        UserRegistrationCreate(
            group_token=token,
            email=f"grace-{workspace.marker}@t.test",
            username=f"grace-{workspace.marker}",
            full_name="Grace",
            password="long-enough-pw",
            password_confirm="long-enough-pw",
        )
    )

    membership = db_session.query(WorkspaceMembers).filter_by(user_id=user.id, group_id=workspace.id).one()
    assert membership.workspace_role == WorkspaceRole.ADMIN
