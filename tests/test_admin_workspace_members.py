"""The admin workspace-members API: removing a member and changing their role.

Regression from 2026-10-07: both read ``membership.username``, which the membership doesn't have (it carries
the user), so removing a member always answered 500 before removing anything, and a role change answered
500 after saving it. The admin workspace page's Remove button now uses this route.
"""

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole


@fixture
def world(db_session):
    """A workspace and a user who is a VIEWER in it; a platform super admin calls."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid, admin_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"awm-{marker}", slug=f"awm-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    for user_id, name, platform_role in ((uid, "awm", "NONE"), (admin_id, "awm-admin", "SUPER_ADMIN")):
        db_session.execute(
            Users.__table__.insert().values(
                id=user_id,
                group_id=gid,
                username=f"{name}-{marker}",
                email=f"{name}-{marker}@t.test",
                full_name=name.upper(),
                password="x",
                is_superuser=platform_role == "SUPER_ADMIN",
                platform_role=platform_role,
                auth_method="MARVIN",
            )
        )
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=admin_id,
        group_id=gid,
        admin=True,
        is_superuser=True,
        username="platform-admin",
        full_name="Platform Admin",
        platform_role=PlatformRole.SUPER_ADMIN,
    )
    client = TestClient(app)
    res = client.post(f"/api/admin/workspaces/{gid}/members", json={"userId": str(uid), "workspaceRole": "VIEWER"})
    assert res.status_code in (200, 201), res.text
    yield SimpleNamespace(client=client, gid=gid, uid=uid, base=f"/api/admin/workspaces/{gid}/members")
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id.in_([uid, admin_id])).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _member_ids(world) -> set[str]:
    res = world.client.get(world.base)
    assert res.status_code == 200, res.text
    return {m["userId"] for m in res.json()}


def test_admin_removes_a_member(world):
    assert str(world.uid) in _member_ids(world)

    res = world.client.delete(f"{world.base}/{world.uid}")

    assert res.status_code == 200, res.text
    assert str(world.uid) not in _member_ids(world)


def test_admin_changes_a_members_role(world):
    res = world.client.put(f"{world.base}/{world.uid}", json={"workspaceRole": "EDITOR"})

    assert res.status_code == 200, res.text
    assert world.client.get(f"{world.base}/{world.uid}").json()["workspaceRole"] == "EDITOR"
