"""The event log's AI-run events follow the AI execution log's rule.

An AI run's events (ai_operation_executed / ai_operation_failed, and approval_requested / granted /
rejected, which carry the paused tool calls' arguments) went to every member through the event log, its
filters, the activity feed the toaster polls, the dashboard's recent activity and the agent's event
tools. Below ADMIN a member now sees them only where they are the event's user; OWNERs/ADMINs and
platform super admins see all of them; AI-run events with no user are admin-only. Every other event is
visible to every member as before.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

EVENTS = "/api/platform/events"
BELOW_ADMIN = [WorkspaceRole.VIEWER, WorkspaceRole.EDITOR]
ADMINS = [WorkspaceRole.ADMIN, WorkspaceRole.OWNER]

# title -> (event_type, whose)
SEEDED = {
    "my run": ("ai_operation_executed", "me"),
    "their run": ("ai_operation_failed", "other"),
    "their approval": ("approval_requested", "other"),
    "system run": ("ai_operation_executed", None),
    "their entry": ("entry_published", "other"),
    "system entry": ("entry_created", None),
}
ALL = set(SEEDED)
MEMBER_VIEW = {"my run", "their entry", "system entry"}


@fixture
def world(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.db.models.users.users import Users

    gid, me, other, entity = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    slug = f"aiev-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    for uid, name in ((me, "me"), (other, "other")):
        db_session.execute(
            Users.__table__.insert().values(
                id=uid,
                group_id=gid,
                username=f"{slug}-{name}",
                email=f"{slug}-{name}@t.test",
                full_name=name,
                password="x",
                is_superuser=False,
                platform_role="NONE",
                auth_method="MARVIN",
            )
        )
    users = {"me": me, "other": other, None: None}
    ids = {}
    now = datetime.now(UTC)
    for i, (title, (event_type, whose)) in enumerate(SEEDED.items()):
        event_id = uuid.uuid4()
        db_session.add(
            EventLogModel(
                event_id=event_id,
                event_type=event_type,
                occurred_at=now - timedelta(seconds=60 - i),
                workspace_id=gid,
                user_id=users[whose],
                entity_id=entity,
                entity_type="entry",
                integration_id="test",
                event_data={"message": {"title": title}, "documentData": {"calls": [{"tool": "revise_entry", "arguments": {"secret": title}}]}},
                message_title=title,
            )
        )
        ids[title] = str(event_id)
    db_session.commit()
    yield SimpleNamespace(gid=gid, me=me, other=other, entity=entity, ids=ids, since=now - timedelta(minutes=5))

    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    db_session.query(EventLogModel).filter(EventLogModel.workspace_id == gid).delete()
    db_session.query(Users).filter(Users.id.in_([me, other])).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _caller(world, role, platform_role=PlatformRole.NONE):
    from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

    def role_in(group_id):
        return role if str(group_id) == str(world.gid) else None

    return SimpleNamespace(
        id=world.me,
        group_id=world.gid,
        active_group_id=world.gid,
        admin=False,
        is_superuser=False,
        full_name="me",
        email="me@t.test",
        platform_role=platform_role,
        workspace_memberships=[SimpleNamespace(group_id=world.gid, workspace_role=role)] if role else [],
        get_workspace_role=role_in,
        has_workspace_role=lambda group_id, required: role_in(group_id) is not None
        and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
    )


def _sign_in(world, role, platform_role=PlatformRole.NONE) -> TestClient:
    user = _caller(world, role, platform_role)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _titles(res) -> set[str]:
    assert res.status_code == 200, res.text
    return {e["messageTitle"] for e in res.json()}


def _views(client, world) -> dict[str, set[str]]:
    """What each event-log surface shows the caller (restricted to the seeded events)."""
    feed = client.get(f"{EVENTS}/feed", params={"since": world.since.isoformat()})
    assert feed.status_code == 200, feed.text
    dashboard = client.get("/api/platform/stats/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    return {
        "list": _titles(client.get(EVENTS, params={"limit": 100})),
        "entity": _titles(client.get(f"{EVENTS}/entity/{world.entity}")),
        "feed": {e["messageTitle"] for e in feed.json()["events"]} & ALL,
        "dashboard": {e["message"] for e in dashboard.json()["recentActivity"]} & ALL,
    }


@pytest.mark.parametrize("role", BELOW_ADMIN)
def test_member_sees_every_non_ai_event_but_only_their_own_ai_runs(world, role):
    assert _views(_sign_in(world, role), world) == dict.fromkeys(("list", "entity", "feed", "dashboard"), MEMBER_VIEW)


@pytest.mark.parametrize("role", ADMINS)
def test_admin_sees_every_event(world, role):
    assert _views(_sign_in(world, role), world) == dict.fromkeys(("list", "entity", "feed", "dashboard"), ALL)


def test_platform_super_admin_sees_every_event(world):
    assert _views(_sign_in(world, None, PlatformRole.SUPER_ADMIN), world)["list"] == ALL


@pytest.mark.parametrize(
    ("role", "expected"), [(WorkspaceRole.VIEWER, {"their entry"}), (WorkspaceRole.ADMIN, {"their run", "their approval", "their entry"})]
)
def test_user_and_type_filters_follow_the_rule(world, role, expected):
    client = _sign_in(world, role)
    assert _titles(client.get(EVENTS, params={"user_id": str(world.other)})) == expected
    assert _titles(client.get(f"{EVENTS}/user/{world.other}")) == expected
    failed = _titles(client.get(EVENTS, params={"event_type": "ai_operation_failed"}))
    assert failed == ({"their run"} if role == WorkspaceRole.ADMIN else set())


@pytest.mark.parametrize("role", BELOW_ADMIN)
def test_member_gets_404_for_another_members_ai_event(world, role):
    client = _sign_in(world, role)
    missing_id = str(uuid.uuid4())
    missing = client.get(f"{EVENTS}/{missing_id}")
    assert missing.status_code == 404
    for title in ("their run", "their approval", "system run"):
        res = client.get(f"{EVENTS}/{world.ids[title]}")
        assert res.status_code == 404, res.text
        assert res.json()["detail"] == missing.json()["detail"].replace(missing_id, world.ids[title])
    for title in ("my run", "their entry", "system entry"):
        assert client.get(f"{EVENTS}/{world.ids[title]}").status_code == 200


def test_admin_reads_any_ai_event(world):
    client = _sign_in(world, WorkspaceRole.ADMIN)
    for title in ("their run", "their approval", "system run"):
        assert client.get(f"{EVENTS}/{world.ids[title]}").status_code == 200


def _tool(db_session, world, name, role, args) -> set[str]:
    from marvin.services.ai.tools.base import ToolContext, get_tool

    ctx = ToolContext(session=db_session, group_id=world.gid, user=_caller(world, role))
    out = json.loads(get_tool(name).handler(ctx, args))
    return {e["title"] for e in out["events"]} & ALL


@pytest.mark.parametrize(("role", "expected"), [(WorkspaceRole.VIEWER, MEMBER_VIEW), (WorkspaceRole.ADMIN, ALL)])
def test_event_tools_follow_the_rule(db_session, world, role, expected):
    assert _tool(db_session, world, "list_events", role, {"limit": 100}) == expected
    assert _tool(db_session, world, "get_entity_history", role, {"entity_id": str(world.entity)}) == expected
