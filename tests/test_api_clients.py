"""API client admin routes: only workspace OWNERs/ADMINs (and platform super admins) may see or manage
them, editing permissions sticks, deleting needs a disabled client, and the admin UI's permission list
is exactly what the publishing routes enforce."""

import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.core.permissions import Permissions
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

BASE = "/api/platform/api-clients"
REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_PERMISSIONS = REPO_ROOT / "frontend" / "src" / "lib" / "apiClientPermissions.ts"


@fixture
def workspace(db_session):
    """A workspace with one user in it; tests sign that user in with whatever role they need."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.api_clients import APIClients
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"ac-{marker}", slug=f"ac-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"ac-{marker}",
            email=f"ac-{marker}@t.test",
            full_name="AC",
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
    db_session.query(APIClients).filter(APIClients.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _sign_in(workspace, role: WorkspaceRole | None = WorkspaceRole.OWNER, platform_role: PlatformRole = PlatformRole.NONE) -> TestClient:
    """Make the workspace's user the caller, holding `role` in it (None = not a member)."""
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=workspace.uid,
        group_id=workspace.gid,
        active_group_id=workspace.gid,
        admin=False,
        is_superuser=False,
        full_name="AC",
        platform_role=platform_role,
        get_workspace_role=lambda group_id: role if str(group_id) == str(workspace.gid) else None,
    )
    return TestClient(app)


@fixture
def signed_in(workspace):
    """The workspace's OWNER is the caller."""
    return _sign_in(workspace)


def _create(client: TestClient, name: str = "Site") -> dict:
    res = client.post(BASE, json={"name": name, "permissions": {Permissions.READ_PUBLISHED_ENTRIES: True}})
    assert res.status_code == 201, res.text
    return res.json()


def test_patch_api_client_permissions_persists(signed_in):
    created = _create(signed_in)
    wanted = {Permissions.READ_PUBLISHED_ENTRIES: True, Permissions.WRITE_FORM_SUBMISSIONS: True}

    res = signed_in.patch(f"{BASE}/{created['id']}", json={"name": "Site v2", "description": "Main site", "permissions": wanted})

    assert res.status_code == 200, res.text
    stored = signed_in.get(f"{BASE}/{created['id']}").json()
    assert (stored["name"], stored["description"], stored["permissions"]) == ("Site v2", "Main site", wanted)


def test_patch_api_client_without_permissions_keeps_them(signed_in):
    created = _create(signed_in)

    signed_in.patch(f"{BASE}/{created['id']}", json={"enabled": False})

    stored = signed_in.get(f"{BASE}/{created['id']}").json()
    assert stored["permissions"] == {Permissions.READ_PUBLISHED_ENTRIES: True} and stored["enabled"] is False


def test_delete_enabled_api_client_returns_409(signed_in):
    created = _create(signed_in)

    res = signed_in.delete(f"{BASE}/{created['id']}")

    assert res.status_code == 409
    assert signed_in.get(f"{BASE}/{created['id']}").status_code == 200


def test_delete_disabled_api_client_removes_it(signed_in):
    created = _create(signed_in)
    signed_in.patch(f"{BASE}/{created['id']}", json={"enabled": False})

    res = signed_in.delete(f"{BASE}/{created['id']}")

    assert res.status_code == 200, res.text
    assert signed_in.get(f"{BASE}/{created['id']}").status_code == 404


def test_admin_ui_permission_list_matches_enforced_permissions():
    route_sources = "\n".join(p.read_text() for p in (REPO_ROOT / "src" / "marvin" / "routes").rglob("*.py"))
    enforced = {getattr(Permissions, name) for name in re.findall(r"\bPermissions\.([A-Z_]+)\b", route_sources)}
    offered = set(re.findall(r'key: "([a-z]+:[a-z_]+)"', FRONTEND_PERMISSIONS.read_text()))

    assert offered == enforced


def _manage_lifecycle(client: TestClient) -> list[int]:
    """Exercise every API client route once; return the status codes in order."""
    created = client.post(BASE, json={"name": "Site", "permissions": {Permissions.READ_PUBLISHED_ENTRIES: True}})
    item = f"{BASE}/{created.json()['id']}"
    return [
        created.status_code,
        client.get(BASE).status_code,
        client.get(item).status_code,
        client.get(f"{item}/preview").status_code,
        client.post(f"{item}/rotate-token").status_code,
        client.patch(item, json={"enabled": False}).status_code,
        client.delete(item).status_code,
    ]


SUCCESS = [201, 200, 200, 200, 200, 200, 200]


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
def test_workspace_owner_or_admin_can_manage_api_clients(workspace, role):
    assert _manage_lifecycle(_sign_in(workspace, role)) == SUCCESS


def test_platform_super_admin_can_manage_api_clients_without_membership(workspace):
    assert _manage_lifecycle(_sign_in(workspace, None, PlatformRole.SUPER_ADMIN)) == SUCCESS


MEMBER_ROUTES = [
    ("get", ""),
    ("post", ""),
    ("get", "/{id}"),
    ("patch", "/{id}"),
    ("delete", "/{id}"),
    ("post", "/{id}/rotate-token"),
    ("get", "/{id}/preview"),
]


@pytest.mark.parametrize("role", [WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER, None])
@pytest.mark.parametrize(("method", "path"), MEMBER_ROUTES)
def test_api_client_routes_below_admin_return_403(workspace, role, method, path):
    created = _create(_sign_in(workspace))
    member = _sign_in(workspace, role)
    body = {"name": "Hijack", "permissions": {Permissions.READ_PUBLISHED_ENTRIES: True}} if method in ("post", "patch") else None

    res = member.request(method, BASE + path.format(id=created["id"]), json=body)

    assert res.status_code == 403, res.text


def test_member_patch_leaves_api_client_unchanged(workspace):
    created = _create(_sign_in(workspace))
    _sign_in(workspace, WorkspaceRole.EDITOR).patch(f"{BASE}/{created['id']}", json={"name": "Hijack", "enabled": False})

    stored = _sign_in(workspace).get(f"{BASE}/{created['id']}").json()

    assert (stored["name"], stored["enabled"]) == ("Site", True)
