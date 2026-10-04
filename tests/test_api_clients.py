"""API client admin routes: editing permissions sticks, deleting needs a disabled client, and the admin
UI's permission list is exactly what the publishing routes enforce."""

import re
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.core.permissions import Permissions

BASE = "/api/platform/api-clients"
REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_PERMISSIONS = REPO_ROOT / "frontend" / "src" / "lib" / "apiClientPermissions.ts"


@fixture
def signed_in(db_session):
    """A workspace with one user, who is the signed-in caller."""
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
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uid, group_id=gid, active_group_id=gid, admin=False, is_superuser=False, full_name="AC"
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    db_session.query(APIClients).filter(APIClients.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


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
