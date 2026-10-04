"""Workspace secrets: only workspace OWNERs/ADMINs (and platform super admins) may create, change or
delete them. Members can still list the slugs (no values) — workflow and webhook forms reference them."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

BASE = "/api/groups/secrets"


@fixture
def workspace(db_session):
    """A workspace with one user in it; tests sign that user in with whatever role they need."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.secrets import WorkspaceSecret
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"sec-{marker}", slug=f"sec-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"sec-{marker}",
            email=f"sec-{marker}@t.test",
            full_name="SEC",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    db_session.query(WorkspaceSecret).filter(WorkspaceSecret.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _sign_in(workspace, role: WorkspaceRole | None, platform_role: PlatformRole = PlatformRole.NONE) -> TestClient:
    """Make the workspace's user the caller, holding `role` in it (None = not a member)."""
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="SEC",
        platform_role=platform_role,
        get_workspace_role=lambda group_id: role if str(group_id) == str(workspace.gid) else None,
    )
    return TestClient(app)


def _create(client: TestClient, slug: str = "SITE_KEY") -> dict:
    res = client.post(BASE, json={"name": "Site key", "slug": slug, "value": "s3cret"})
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
def test_owner_or_admin_can_create_update_and_delete_secrets(workspace, role):
    client = _sign_in(workspace, role)
    secret = _create(client)
    assert client.patch(f"{BASE}/{secret['id']}", json={"value": "rotated"}).status_code == 200
    assert client.delete(f"{BASE}/{secret['id']}").status_code == 204


def test_platform_super_admin_can_manage_secrets_without_membership(workspace):
    client = _sign_in(workspace, None, PlatformRole.SUPER_ADMIN)
    secret = _create(client)
    assert client.delete(f"{BASE}/{secret['id']}").status_code == 204


@pytest.mark.parametrize("role", [WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER])
def test_members_below_admin_cannot_write_secrets(workspace, role):
    secret = _create(_sign_in(workspace, WorkspaceRole.OWNER))
    member = _sign_in(workspace, role)

    assert member.post(BASE, json={"name": "X", "slug": "OTHER_KEY", "value": "v"}).status_code == 403
    assert member.patch(f"{BASE}/{secret['id']}", json={"value": "hijacked"}).status_code == 403
    assert member.delete(f"{BASE}/{secret['id']}").status_code == 403
    # Slugs (never values) stay readable for the forms that reference them.
    assert member.get(f"{BASE}/slugs").json() == ["SITE_KEY"]
