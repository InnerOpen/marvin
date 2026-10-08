"""What a 204 No Content answer carries: no body, and no Content-Type (app.MarvinJSONResponse).

Regression from 2026-10-07: every 204 went out with ``content-type: application/json`` on an empty body.
SDK 3.x (the admin UI's) tried to parse it, took the failure for a network error and sent the DELETE
again, whose 404 surfaced as "Resource not found" for a delete that had worked: workflows, secrets,
variables, scheduled tasks, incoming webhooks, integrations and their event subscriptions, MCP servers.
"""

import uuid
from types import SimpleNamespace

from fastapi.datastructures import DefaultPlaceholder
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import MarvinJSONResponse, app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

BASE = "/api/groups/invitations"


@fixture
def owner(db_session):
    """A workspace whose one user, an OWNER, is the caller (revoking an invite answers 204)."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"inv-{marker}", slug=f"inv-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"inv-{marker}",
            email=f"inv-{marker}@t.test",
            full_name="INV",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uid,
        group_id=gid,
        active_group_id=gid,
        admin=False,
        is_superuser=False,
        username=f"inv-{marker}",
        full_name="INV",
        platform_role=PlatformRole.NONE,
        get_workspace_role=lambda group_id: WorkspaceRole.OWNER if str(group_id) == str(gid) else None,
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _invite(client: TestClient) -> dict:
    res = client.post(BASE, json={"usesLeft": 1})
    assert res.status_code == 201, res.text
    return res.json()


def test_no_content_answer_has_no_body_and_no_content_type(owner):
    res = owner.delete(f"{BASE}/{_invite(owner)['id']}")

    assert res.status_code == 204
    assert res.content == b""
    assert "content-type" not in res.headers


def test_every_204_route_answers_without_a_content_type():
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.status_code == 204]
    assert routes
    for route in routes:
        response_class = route.response_class
        if isinstance(response_class, DefaultPlaceholder):
            response_class = response_class.value
        assert "content-type" not in response_class(None, status_code=204).headers, route.path


def test_json_answers_keep_their_content_type():
    assert MarvinJSONResponse({"ok": True}).headers["content-type"] == "application/json"
    assert MarvinJSONResponse(None, status_code=200).headers["content-type"] == "application/json"
