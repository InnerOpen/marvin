"""Platform events leave the workspace Event Log for the admin Events page.

Sign-ups, workspaces created, edited or deleted by a platform admin, a user switching workspace, personal tokens,
the platform's security signals and backups are `scope="platform"` in the catalog. They're still dispatched and
stored with the workspace they touched, but every workspace read of the log leaves them out (the log and its
filters, single events, entity and user history, the activity feed, the dashboard, workflow dry-run samples, the
agent's event tools). The super-admin `GET /api/admin/events` lists exactly those, across workspaces, with filters.
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
from marvin.services.events.event_catalog import _PLATFORM_SCOPE, CATALOG, PLATFORM_EVENT_TYPES, get_catalog_entry, is_platform_event
from tests.workflow_fakes import fake_workflow

EVENTS = "/api/platform/events"
ADMIN_EVENTS = "/api/admin/events"

EXPECTED_PLATFORM = {
    "user_signup",
    "user_updated",
    "user_deleted",
    "user_password_reset_requested",
    "user_password_reset_completed",
    "token_refreshed",
    "workspace_created",
    "workspace_updated",
    "workspace_deleted",
    "workspace_activated",
    "api_token_created",
    "api_token_rotated",
    "api_token_revoked",
    "api_rate_limit_exceeded",
    "login_failed_multiple_times",
    "suspicious_activity_detected",
    "backup_started",
    "backup_completed",
    "backup_failed",
}

# title -> (event_type, whose, workspace, minutes ago)
SEEDED = {
    "signup": ("user_signup", None, "a", 1),
    "created": ("workspace_created", "me", "a", 2),
    "activated": ("workspace_activated", "me", "a", 3),
    "reset": ("user_password_reset_requested", None, "b", 4),
    "old created": ("workspace_created", "me", "b", 60 * 24 * 3),
    "entry": ("entry_published", "me", "a", 5),
    "settings": ("workspace_settings_changed", "me", "a", 6),
}
PLATFORM_TITLES = {t for t, (et, *_) in SEEDED.items() if et in EXPECTED_PLATFORM}
WORKSPACE_A = {t for t, (et, _, ws, _) in SEEDED.items() if ws == "a" and et not in EXPECTED_PLATFORM}


# ── catalog ─────────────────────────────────────────────────────────────────


def test_every_catalog_entry_has_a_valid_scope():
    assert {e.scope for e in CATALOG} <= {"workspace", "platform"}
    assert [e.event_type for e in CATALOG if e.scope not in ("workspace", "platform")] == []


def test_platform_scope_is_the_decided_list():
    assert PLATFORM_EVENT_TYPES == EXPECTED_PLATFORM
    # Every name in the gate is a catalog entry: a typo would silently leave an event in workspace logs.
    assert {t for t in _PLATFORM_SCOPE if get_catalog_entry(t) is None} == set()


STAY_IN_WORKSPACE = ["member_added", "invitation_sent", "workspace_settings_changed", "secret_created", "variable_updated"]


@pytest.mark.parametrize("event_type", [*STAY_IN_WORKSPACE, "storage_quota_warning", "api_client_created"])
def test_workspace_events_stay_in_the_workspace(event_type):
    assert get_catalog_entry(event_type).scope == "workspace"
    assert not is_platform_event(event_type)


def test_dispatched_but_formerly_uncatalogued_types_are_catalogued():
    for event_type in ("workspace_activated", "token_refreshed"):
        entry = get_catalog_entry(event_type)
        assert entry is not None and entry.scope == "platform" and entry.audit_locked


def test_workspace_updated_is_only_emitted_by_the_admin_controller():
    """workspace_updated is platform scope because only the platform admin's workspace controller emits it.
    A second emitter (a workspace admin renaming their own workspace) would make that wrong."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "marvin"
    emitters = sorted(str(f.relative_to(root)) for f in root.rglob("*.py") if "EventTypes.workspace_updated" in f.read_text())
    assert emitters == ["routes/admin/group_controller.py"]


# ── fixtures ────────────────────────────────────────────────────────────────


def _insert_user(db_session, uid, gid, slug, name):
    from marvin.db.models.users.users import Users

    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"{slug}-{name}",
            email=f"{slug}-{name}@t.test",
            full_name=f"{name.title()} Person",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )


@fixture
def world(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.db.models.users.users import Users

    ga, gb, me, newbie, entity = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    slug = f"adev-{ga.hex[:8]}"
    groups = {"a": ga, "b": gb}
    for key, gid in groups.items():
        group = Groups(session=db_session, name=f"{slug}-{key}", slug=f"{slug}-{key}")
        group.id = gid
        db_session.add(group)
    db_session.flush()
    _insert_user(db_session, me, ga, slug, "me")
    _insert_user(db_session, newbie, ga, slug, "newbie")

    now = datetime.now(UTC)
    ids, row_ids = {}, {}
    for title, (event_type, whose, ws, minutes) in SEEDED.items():
        event_id, row_id = uuid.uuid4(), uuid.uuid4()
        signup = event_type == "user_signup"
        db_session.add(
            EventLogModel(
                id=row_id,
                event_id=event_id,
                event_type=event_type,
                occurred_at=now - timedelta(minutes=minutes),
                workspace_id=groups[ws],
                user_id=me if whose == "me" else None,
                # A sign-up names the new account as its entity; the rest share one entity for the history route.
                entity_id=newbie if signup else entity,
                entity_type="user" if signup else "entry",
                integration_id="test",
                event_data={
                    "message": {"title": title},
                    "documentData": {"email": f"{slug}-reset@t.test", "username": "resetter"} if event_type.startswith("user_password") else {},
                },
                message_title=title,
            )
        )
        ids[title], row_ids[title] = str(event_id), str(row_id)
    db_session.commit()
    yield SimpleNamespace(ga=ga, gb=gb, me=me, newbie=newbie, entity=entity, slug=slug, ids=ids, row_ids=row_ids, since=now - timedelta(minutes=10))

    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    db_session.query(EventLogModel).filter(EventLogModel.workspace_id.in_([ga, gb])).delete(synchronize_session=False)
    db_session.query(Users).filter(Users.id.in_([me, newbie])).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.id.in_([ga, gb])).delete(synchronize_session=False)
    db_session.commit()


def _caller(world, role, platform_role=PlatformRole.NONE):
    from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

    def role_in(group_id):
        return role if str(group_id) == str(world.ga) else None

    return SimpleNamespace(
        id=world.me,
        group_id=world.ga,
        active_group_id=world.ga,
        admin=False,
        is_superuser=False,
        username=f"{world.slug}-me",
        full_name="Me Person",
        email=f"{world.slug}-me@t.test",
        platform_role=platform_role,
        workspace_memberships=[SimpleNamespace(group_id=world.ga, workspace_role=role)] if role else [],
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
    return {e["messageTitle"] for e in res.json()} & set(SEEDED)


# ── the workspace's reads leave platform events out ─────────────────────────


@pytest.mark.parametrize("role", [WorkspaceRole.VIEWER, WorkspaceRole.OWNER])
def test_workspace_log_surfaces_leave_platform_events_out(world, role):
    client = _sign_in(world, role)
    feed = client.get(f"{EVENTS}/feed", params={"since": world.since.isoformat()})
    assert feed.status_code == 200, feed.text
    dashboard = client.get("/api/platform/stats/dashboard")
    assert dashboard.status_code == 200, dashboard.text

    assert _titles(client.get(EVENTS, params={"limit": 100})) == WORKSPACE_A
    assert {e["messageTitle"] for e in feed.json()["events"]} & set(SEEDED) == WORKSPACE_A
    assert {e["message"] for e in dashboard.json()["recentActivity"]} & set(SEEDED) == WORKSPACE_A
    assert _titles(client.get(f"{EVENTS}/entity/{world.entity}")) == WORKSPACE_A
    assert _titles(client.get(f"{EVENTS}/user/{world.me}")) == WORKSPACE_A
    # Asking for a platform type by name finds nothing either.
    assert _titles(client.get(EVENTS, params={"event_type": "workspace_created"})) == set()
    assert _titles(client.get(f"{EVENTS}/entity/{world.newbie}")) == set()


def test_a_platform_event_is_a_404_in_the_workspace(world):
    client = _sign_in(world, WorkspaceRole.OWNER)
    missing_id = str(uuid.uuid4())
    missing = client.get(f"{EVENTS}/{missing_id}")
    for title in ("signup", "created", "activated"):
        res = client.get(f"{EVENTS}/{world.ids[title]}")
        assert res.status_code == 404, res.text
        assert res.json()["detail"] == missing.json()["detail"].replace(missing_id, world.ids[title])
    assert client.get(f"{EVENTS}/{world.ids['entry']}").status_code == 200


def test_event_tools_leave_platform_events_out(db_session, world):
    from marvin.services.ai.tools.base import ToolContext, get_tool

    ctx = ToolContext(session=db_session, group_id=world.ga, user=_caller(world, WorkspaceRole.OWNER))

    def titles(name, args):
        return {e["title"] for e in json.loads(get_tool(name).handler(ctx, args))["events"]} & set(SEEDED)

    assert titles("list_events", {"limit": 100}) == WORKSPACE_A
    assert titles("list_events", {"event_type": "user_signup"}) == set()
    assert titles("get_entity_history", {"entity_id": str(world.entity)}) == WORKSPACE_A


def test_workflow_dry_run_samples_leave_platform_events_out(db_session, world):
    from marvin.services.automation import samples

    def automation(event):
        return fake_workflow(definition={"trigger": {"type": "event", "event": event}})

    assert samples.list_samples(db_session, world.ga, automation("workspace_created")) == []
    assert samples.default_sample(db_session, world.ga, automation("workspace_created")) is None
    with pytest.raises(samples.SampleNotFound):
        samples.resolve_sample(db_session, world.ga, automation("workspace_created"), event_id=world.row_ids["created"])
    # A workspace event still samples.
    picked = samples.list_samples(db_session, world.ga, automation("entry_published"))
    assert [s.label for s in picked if s.label in SEEDED] == ["entry"]


# ── the admin Events page ───────────────────────────────────────────────────


def _admin(world) -> TestClient:
    return _sign_in(world, None, PlatformRole.SUPER_ADMIN)


def _page(client, **params) -> dict:
    res = client.get(ADMIN_EVENTS, params={"per_page": 100, **params})
    assert res.status_code == 200, res.text
    return res.json()


def _seeded(page) -> list[dict]:
    return [e for e in page["items"] if e["messageTitle"] in SEEDED]


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.VIEWER])
def test_admin_events_are_super_admin_only(world, role):
    client = _sign_in(world, role)
    assert client.get(ADMIN_EVENTS).status_code == 403
    assert client.get(f"{ADMIN_EVENTS}/catalog").status_code == 403
    assert client.get(f"{ADMIN_EVENTS}/{world.ids['signup']}").status_code == 403


def test_admin_lists_platform_events_across_workspaces_newest_first(world):
    rows = _seeded(_page(_admin(world)))
    assert [r["messageTitle"] for r in rows] == ["signup", "created", "activated", "reset", "old created"]

    by_title = {r["messageTitle"]: r for r in rows}
    created = by_title["created"]
    assert created["eventName"] == "Workspace Created"
    assert created["workspaceId"] == str(world.ga) and created["workspaceName"] == f"{world.slug}-a"
    assert created["workspaceSlug"] == f"{world.slug}-a"
    assert created["userName"] == "Me Person" and created["userEmail"] == f"{world.slug}-me@t.test"
    # A sign-up has no signed-in user: the account it names.
    signup = by_title["signup"]
    assert signup["userId"] == str(world.newbie) and signup["userName"] == "Newbie Person"
    # A password reset names its account only in the payload.
    reset = by_title["reset"]
    assert reset["userId"] is None and reset["userEmail"] == f"{world.slug}-reset@t.test" and reset["userName"] == "resetter"
    assert reset["workspaceName"] == f"{world.slug}-b"
    assert "eventData" not in created


def test_admin_filters(world):
    client = _admin(world)
    titles = lambda **p: [r["messageTitle"] for r in _seeded(_page(client, **p))]  # noqa: E731

    assert titles(event_type="workspace_created") == ["created", "old created"]
    assert titles(workspace_id=str(world.gb)) == ["reset", "old created"]
    assert titles(workspace_id=str(world.ga), event_type="workspace_created") == ["created"]
    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert titles(start_date=since, workspace_id=str(world.gb)) == ["reset"]
    until = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    assert titles(end_date=until, workspace_id=str(world.gb)) == ["old created"]
    # A workspace event type isn't on this page at all.
    assert titles(event_type="entry_published") == []
    assert _page(client, event_type="entry_published", workspace_id=str(world.ga))["total"] == 0


def test_admin_paginates(world):
    client = _admin(world)
    first = _page(client, workspace_id=str(world.ga), per_page=2, page=1)
    second = _page(client, workspace_id=str(world.ga), per_page=2, page=2)
    assert first["total"] == 3 and first["total_pages"] == 2 and first["per_page"] == 2  # PaginationBase keeps snake_case
    assert [r["messageTitle"] for r in first["items"]] == ["signup", "created"]
    assert [r["messageTitle"] for r in second["items"]] == ["activated"]
    assert client.get(ADMIN_EVENTS, params={"per_page": 101}).status_code == 422
    assert client.get(ADMIN_EVENTS, params={"page": 0}).status_code == 422


def test_admin_reads_one_platform_event_with_its_payload(world):
    client = _admin(world)
    res = client.get(f"{ADMIN_EVENTS}/{world.ids['reset']}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["eventType"] == "user_password_reset_requested" and body["eventData"]["documentData"]["username"] == "resetter"
    # A workspace event is in its workspace's log, not here.
    assert client.get(f"{ADMIN_EVENTS}/{world.ids['entry']}").status_code == 404
    assert client.get(f"{ADMIN_EVENTS}/{uuid.uuid4()}").status_code == 404


def test_admin_catalog_lists_the_platform_types(world):
    res = _admin(world).get(f"{ADMIN_EVENTS}/catalog")
    assert res.status_code == 200, res.text
    rows = res.json()
    # Hidden ones (nothing sends them: the security signals, user_updated/_deleted, backups…) aren't listed.
    assert {r["eventType"] for r in rows} == {t for t in EXPECTED_PLATFORM if not get_catalog_entry(t).hidden}
    assert "api_token_created" in {r["eventType"] for r in rows} and "suspicious_activity_detected" not in {r["eventType"] for r in rows}
    assert set(rows[0]) == {"eventType", "name", "description", "category"}
    assert rows[0]["category"] == "Authentication"


# ── still dispatched and stored ─────────────────────────────────────────────


def test_a_platform_event_is_still_dispatched_and_stored(db_session, world):
    """Creating a workspace through the admin API still writes workspace_created, with the new workspace's id;
    the admin page lists it and that workspace's own log doesn't."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.services.group.group_purge import purge_group_dependents

    client = _admin(world)
    name = f"{world.slug}-new"
    res = client.post("/api/admin/groups", json={"name": name})
    assert res.status_code == 201, res.text
    new_id = uuid.UUID(res.json()["id"])
    try:
        db_session.expire_all()
        stored = db_session.query(EventLogModel).filter(EventLogModel.workspace_id == new_id, EventLogModel.event_type == "workspace_created").all()
        assert len(stored) == 1

        listed = _page(client, workspace_id=str(new_id), event_type="workspace_created")
        assert listed["total"] == 1 and listed["items"][0]["workspaceName"] == name

        from marvin.repos.platform.event_log import EventLogRepository

        assert [e for e in EventLogRepository(db_session, new_id).get_by_workspace(new_id) if e.event_type == "workspace_created"] == []
    finally:
        db_session.rollback()
        purge_group_dependents(db_session, new_id)
        db_session.query(Groups).filter(Groups.id == new_id).delete()
        db_session.commit()
