"""A personal API token can be pinned to one workspace when it is created (or left global, as before).

A pinned token is its owner as seen from that workspace alone: it reaches only that workspace whatever the person's active
workspace is, has no platform-admin reach, and cannot manage tokens or the account, so it cannot mint a wider one.
"""

import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import select

from marvin.app import app
from marvin.db.models.groups import Groups
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.users.users import LongLiveToken, Users
from marvin.db.models.users.workspace_members import WorkspaceMembers
from tests.test_no_workspace import _client, _group, _join, _user


@pytest.fixture
def pins(db_session):
    """A person in two workspaces (active in beta), a super admin in alpha, and a workspace the person is not in."""
    marker = uuid.uuid4().hex[:8]
    alpha, beta, outside = (_group(db_session, f"{n}-{marker}") for n in ("Alpha", "Beta", "Outside"))
    person = _user(db_session, f"{marker}-p", home=alpha.id, active=beta.id)
    _join(db_session, person, alpha, "OWNER")
    _join(db_session, person, beta, "OWNER")
    admin = _user(db_session, f"{marker}-a", super_admin=True, home=alpha.id)
    _join(db_session, admin, alpha, "OWNER")
    db_session.commit()
    yield SimpleNamespace(alpha=alpha, beta=beta, outside=outside, person=person, admin=admin, me=_client(person), boss=_client(admin))
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    ids = db_session.execute(select(Users.id).where(Users.username.like(f"nw-{marker}%"))).scalars().all()
    db_session.execute(sa.delete(EventLogModel).where(EventLogModel.user_id.in_(ids)))
    db_session.execute(sa.delete(LongLiveToken).where(LongLiveToken.user_id.in_(ids)))
    db_session.execute(sa.delete(WorkspaceMembers).where(WorkspaceMembers.user_id.in_(ids)))
    db_session.execute(sa.delete(Users).where(Users.id.in_(ids)))
    for group in (alpha, beta, outside):
        purge_group_dependents(db_session, group.id)
        db_session.delete(db_session.get(Groups, group.id))
    db_session.commit()


def _mint(client: TestClient, **body) -> dict:
    res = client.post("/api/self/api-tokens", json={"name": "t", **body})
    assert res.status_code in (200, 201), res.text
    return res.json()


def _as(token: dict) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})


def test_a_token_made_without_a_workspace_is_global_and_follows_the_active_workspace(pins):
    token = _mint(pins.me)
    assert token.get("groupId") is None
    current = _as(token).get("/api/self/workspaces/current").json()
    assert current["id"] == str(pins.beta.id)  # the person's active workspace, as before


def test_a_pinned_token_reaches_only_its_workspace_even_when_another_is_active(pins):
    token = _mint(pins.me, groupId=str(pins.alpha.id))
    assert token["groupId"] == str(pins.alpha.id)
    api = _as(token)
    assert api.get("/api/self/workspaces/current").json()["id"] == str(pins.alpha.id)  # not beta, the person's active one
    listed = api.get("/api/self/workspaces").json()
    assert [w["workspace"]["id"] for w in listed] == [str(pins.alpha.id)]
    assert api.get("/api/platform/entries").status_code == 200


def test_a_token_cannot_be_pinned_to_a_workspace_the_person_is_not_in(pins):
    res = pins.me.post("/api/self/api-tokens", json={"name": "t", "groupId": str(pins.outside.id)})
    assert res.status_code in (403, 404), res.text
    assert pins.me.post("/api/self/api-tokens", json={"name": "t", "groupId": str(uuid.uuid4())}).status_code in (403, 404)


def test_a_pinned_token_has_no_platform_admin_reach_but_the_same_admins_global_token_does(pins):
    pinned, global_ = _mint(pins.boss, groupId=str(pins.alpha.id)), _mint(pins.boss)
    assert _as(global_).get("/api/admin/about").status_code == 200
    assert _as(pinned).get("/api/admin/about").status_code in (401, 403)


def test_a_pinned_token_cannot_mint_manage_or_switch(pins):
    api = _as(_mint(pins.me, groupId=str(pins.alpha.id)))
    assert api.post("/api/self/api-tokens", json={"name": "wider"}).status_code == 403  # no escaping the pin
    assert api.get("/api/self/api-tokens").status_code == 403
    switch = api.put("/api/self/workspaces/current", json={"workspace": str(pins.beta.id)})  # the person is in beta, so only the pin refuses
    assert switch.status_code == 403, switch.text
    assert api.get("/api/self/workspaces/current").json()["id"] == str(pins.alpha.id)


def test_a_pinned_token_stops_working_when_its_owner_leaves_the_workspace(pins, db_session):
    api = _as(_mint(pins.me, groupId=str(pins.alpha.id)))
    assert api.get("/api/platform/entries").status_code == 200
    db_session.execute(sa.delete(WorkspaceMembers).where(WorkspaceMembers.user_id == pins.person.id, WorkspaceMembers.group_id == pins.alpha.id))
    db_session.commit()
    assert api.get("/api/platform/entries").status_code in (401, 403)


def test_the_token_list_says_which_workspace_each_is_pinned_to(pins):
    _mint(pins.me, groupId=str(pins.alpha.id))
    _mint(pins.me)
    rows = pins.me.get("/api/self/api-tokens").json()
    assert sorted(str(r.get("groupId")) for r in rows) == sorted([str(pins.alpha.id), "None"])


def test_deleting_the_workspace_deletes_its_pinned_tokens_rather_than_widening_them(db_session):
    column = LongLiveToken.__table__.c.group_id
    assert [fk.ondelete for fk in column.foreign_keys] == ["CASCADE"] and column.nullable is True


def test_the_long_lived_jwt_form_of_a_pinned_token_is_scoped_too(pins, db_session):
    from marvin.core.dependencies.dependencies import validate_long_live_token

    token = _mint(pins.me, groupId=str(pins.alpha.id))
    view = validate_long_live_token(db_session, token["token"], str(pins.person.id))
    assert view.token_workspace_id == pins.alpha.id and [m.group_id for m in view.workspace_memberships] == [pins.alpha.id]
    assert view.active_group_id == pins.alpha.id


def test_a_pinned_token_cannot_create_a_workspace(pins):
    api = _as(_mint(pins.boss, groupId=str(pins.alpha.id)))
    res = api.post("/api/admin/groups", json={"name": "Elsewhere"})
    assert res.status_code == 403, res.text
