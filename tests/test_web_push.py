"""Web Push for the admin app (services/web_push.py, services/push_notifications.py, the Push channel of
services/alerting.py, /api/self/push).

Off without VAPID settings: nothing to subscribe to, nothing sent, alert channels unchanged. With them, a
signed-in user manages only their own devices and chooses which kinds of push they take; the sender prunes
devices the push service says are gone and counts other failures; and each source reaches only the people
it's for — the run's owner for an AI approval, the workspace's editors and above for a form submission or a
waiting scheduled publish, owners and admins for workspace notifications (once per incident), super admins
for platform alerts. Nothing reaches a real push service: ``_post`` is captured, and the one test that goes
through pywebpush stubs ``requests.post``.
"""

import base64
import json
import os
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services import alerting, push_notifications, web_push
from marvin.services import platform_alerts as platform
from marvin.services import workspace_alerts as notes
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import (
    EventAIApprovalData,
    EventAutomationData,
    EventBackupData,
    EventFormSubmissionData,
    EventOperation,
    EventScheduledPublishBlockedData,
    EventTypes,
)

API = "/api/self/push"
SOURCE = "test_web_push"
ROLES = ("owner", "admin", "editor", "author", "viewer")
WORKFLOW_ID = uuid.UUID("00000000-0000-4000-8000-00000000b001")
REAL_POST = web_push._post


# ── world ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def world(db_session, monkeypatch):
    """A workspace with one member per role, two super admins (no membership) and the owner of another
    workspace; every push is captured instead of posted."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.alert_incidents import WorkspaceAlertIncidentModel
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.db.models.platform.platform_settings import PlatformSettingsModel
    from marvin.db.models.users.push_subscriptions import PushSubscriptionModel
    from marvin.db.models.users.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    gid, other = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    for key, g_id in (("ws", gid), ("other", other)):
        group = Groups(session=db_session, name=f"wp-{key}-{marker}", slug=f"wp-{key}-{marker}")
        group.id = g_id
        db_session.add(group)
    db_session.flush()
    for g_id in (gid, other):
        if db_session.query(GroupPreferencesModel).filter_by(group_id=g_id).first() is None:
            db_session.add(GroupPreferencesModel(session=db_session, group_id=g_id))
    users: dict[str, uuid.UUID] = {}
    people = [(r, gid, "NONE", r) for r in ROLES] + [("super1", gid, "SUPER_ADMIN", None), ("super2", gid, "SUPER_ADMIN", None)]
    people.append(("outsider", other, "NONE", "owner"))
    for name, g_id, platform_role, role in people:
        uid = uuid.uuid4()
        users[name] = uid
        db_session.execute(
            sa.insert(Users.__table__).values(
                id=uid,
                group_id=g_id,
                full_name=f"{name.title()} Person",
                username=f"{name}-{marker}",
                email=f"{name}-{marker}@example.test",
                password="x",
                auth_method="MARVIN",
                is_superuser=False,
                platform_role=platform_role,
                admin=False,
            )
        )
        if role:
            db_session.execute(
                sa.insert(WorkspaceMembers.__table__).values(id=uuid.uuid4(), user_id=uid, group_id=g_id, workspace_role=WorkspaceRole[role.upper()])
            )
    db_session.commit()

    pushes: list[tuple[str, dict]] = []  # (endpoint, payload) — every push "sent"
    answers: dict[str, int] = {}  # endpoint → the status the push service answers (201 when absent)

    def fake_post(sub, data, message, vapid):
        pushes.append((sub.endpoint, json.loads(data)))
        return answers.get(sub.endpoint, 201)

    monkeypatch.setattr(web_push, "_post", fake_post)
    monkeypatch.setattr(notes, "smtp_ready", lambda session, group_id: False)
    monkeypatch.setattr(platform, "smtp_ready", lambda: False)
    monkeypatch.setattr(platform, "_platform_workspace", lambda session: session.get(Groups, gid))
    yield SimpleNamespace(gid=gid, other=other, marker=marker, users=users, pushes=pushes, answers=answers)

    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    ids = list(users.values())
    db_session.query(PushSubscriptionModel).filter(PushSubscriptionModel.user_id.in_(ids)).delete(synchronize_session=False)
    db_session.query(WorkspaceAlertIncidentModel).filter(WorkspaceAlertIncidentModel.group_id.in_([gid, other])).delete(synchronize_session=False)
    db_session.query(EventLogModel).filter(EventLogModel.integration_id.in_([SOURCE, "notifications", "platform_settings"])).delete(
        synchronize_session=False
    )
    db_session.query(EventLogModel).filter(EventLogModel.workspace_id.in_([gid, other])).delete(synchronize_session=False)
    db_session.query(PlatformSettingsModel).filter(PlatformSettingsModel.key.in_([platform.SETTINGS_KEY, platform.STATUS_KEY])).delete(
        synchronize_session=False
    )
    db_session.query(WorkspaceMembers).filter(WorkspaceMembers.group_id.in_([gid, other])).delete(synchronize_session=False)
    db_session.query(Users).filter(Users.id.in_(ids)).delete(synchronize_session=False)
    db_session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id.in_([gid, other])).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.id.in_([gid, other])).delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def vapid(monkeypatch):
    """Web Push configured with a freshly generated key pair (never a real one)."""
    from marvin.core.config import get_app_settings
    from marvin.scripts.vapid import generate

    public, private = generate()
    settings = get_app_settings()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:ops@example.test")
    return SimpleNamespace(public=public, private=private)


def _sign_in(world, name: str) -> TestClient:
    uid = world.users[name]
    super_admin = name.startswith("super")
    role = None if super_admin or name == "outsider" else WorkspaceRole[name.upper()]
    group_id = world.other if name == "outsider" else world.gid
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uid,
        group_id=group_id,
        active_group_id=group_id,
        admin=False,
        is_superuser=False,
        full_name=f"{name.title()} Person",
        username=f"{name}-{world.marker}",
        email=f"{name}-{world.marker}@example.test",
        platform_role=PlatformRole.SUPER_ADMIN if super_admin else PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=group_id, workspace_role=role)] if role else [],
        get_workspace_role=lambda g: role if str(g) == str(group_id) else None,
    )
    return TestClient(app)


def _device(name: str, n: int = 1) -> dict:
    return {"endpoint": f"https://push.example.test/{name}/{n}", "keys": {"p256dh": f"p256-{name}-{n}", "auth": f"auth-{name}-{n}"}}


def _subscribe(db_session, world, *names: str) -> None:
    """Give each named user one device, straight through the service."""
    from marvin.db.models.users.users import Users

    for name in names:
        user = db_session.get(Users, world.users[name])
        d = _device(name)
        web_push.subscribe(db_session, user, endpoint=d["endpoint"], p256dh=d["keys"]["p256dh"], auth=d["keys"]["auth"], user_agent=None, label=None)


def _reached(world) -> set[str]:
    """Who got a push: the names in the endpoints captured."""
    return {endpoint.split("/")[-2] for endpoint, _ in world.pushes}


def _prefer(db_session, world, name: str, **choices: bool) -> None:
    from marvin.db.models.users.users import Users

    web_push.set_preferences(db_session, db_session.get(Users, world.users[name]), choices)


# ── off without VAPID ─────────────────────────────────────────────────────────────


def test_push_is_off_without_vapid(db_session, world):
    assert not web_push.configured()
    client = _sign_in(world, "editor")
    body = client.get(API).json()
    assert body["enabled"] is False and body["publicKey"] is None and body["devices"] == []
    assert client.post(f"{API}/subscriptions", json=_device("editor")).status_code == 409
    assert client.post(f"{API}/test").status_code == 409

    # alert channels are exactly what they were: no push channel, nothing pushed
    assert notes.channels_for(db_session, world.gid, "workflow_failed") == ["email"]
    _subscribe(db_session, world, "owner")
    _workflow(world, ok=False)
    assert world.pushes == []
    assert "push" not in notes.load(db_session, world.gid).channels_for("workflow_failed")


# ── devices: self-scoped ────────────────────────────────────────────────────────────


def test_devices_are_self_scoped(db_session, world, vapid):
    editor = _sign_in(world, "editor")
    created = editor.post(f"{API}/subscriptions", json=_device("editor"), headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/130.0"})
    assert created.status_code == 201, created.text
    device = created.json()
    assert device["label"] == "Chrome on Android"
    body = editor.get(API).json()
    assert body["enabled"] is True and body["publicKey"] == vapid.public
    assert [d["id"] for d in body["devices"]] == [device["id"]]

    author = _sign_in(world, "author")
    assert author.get(API).json()["devices"] == []
    assert author.delete(f"{API}/subscriptions/{device['id']}").status_code == 404
    assert author.delete(f"{API}/subscriptions", params={"endpoint": device["endpoint"]}).status_code == 204  # not theirs: nothing happens
    assert len(web_push.devices(db_session, world.users["editor"])) == 1

    editor = _sign_in(world, "editor")
    assert editor.delete(f"{API}/subscriptions/{device['id']}").status_code == 204
    assert editor.get(API).json()["devices"] == []


def test_subscribing_upserts_by_endpoint_and_a_device_changes_hands(db_session, world, vapid):
    first = _sign_in(world, "editor").post(f"{API}/subscriptions", json=_device("shared")).json()
    again = _sign_in(world, "editor").post(f"{API}/subscriptions", json={**_device("shared"), "label": "Kitchen iPad"}).json()
    assert again["id"] == first["id"] and again["label"] == "Kitchen iPad"

    # someone else signs in on the same browser and turns push on: the device is theirs now
    moved = _sign_in(world, "author").post(f"{API}/subscriptions", json=_device("shared")).json()
    assert moved["id"] == first["id"]
    assert web_push.devices(db_session, world.users["editor"]) == []
    assert [str(d.id) for d in web_push.devices(db_session, world.users["author"])] == [first["id"]]

    # a rotated subscription replaces the old endpoint
    rotated = _sign_in(world, "author").post(f"{API}/subscriptions", json={**_device("shared", 2), "replaces": _device("shared")["endpoint"]})
    assert rotated.status_code == 201
    assert [d.endpoint for d in web_push.devices(db_session, world.users["author"])] == [_device("shared", 2)["endpoint"]]


def test_endpoint_must_be_a_public_https_url_in_production(world, vapid, monkeypatch):
    from marvin.core.config import get_app_settings

    client = _sign_in(world, "editor")
    bad = {**_device("x"), "endpoint": "ftp://push.example.test/x"}
    assert client.post(f"{API}/subscriptions", json=bad).status_code == 422
    monkeypatch.setattr(get_app_settings(), "PRODUCTION", True)
    for endpoint in ("http://push.example.test/x", "https://127.0.0.1/x", "https://10.1.2.3/x", "https://localhost/x"):
        assert client.post(f"{API}/subscriptions", json={**_device("x"), "endpoint": endpoint}).status_code == 422, endpoint
    assert web_push.endpoint_problem("https://93.184.216.34/push") is None


def test_preferences_default_on_and_platform_alerts_are_for_super_admins(db_session, world, vapid):
    editor = _sign_in(world, "editor")
    cats = {c["key"]: c["enabled"] for c in editor.get(API).json()["categories"]}
    assert cats == {"activity": True, "approvals": True, "workspace_alerts": True, "trash_reminders": True}
    saved = editor.put(f"{API}/preferences", json={"categories": {"activity": False, "platform_alerts": True, "nonsense": True}}).json()
    assert {c["key"]: c["enabled"] for c in saved["categories"]} == {
        "activity": False,
        "approvals": True,
        "workspace_alerts": True,
        "trash_reminders": True,
    }
    supers = {c["key"] for c in _sign_in(world, "super1").get(API).json()["categories"]}
    assert "platform_alerts" in supers


def test_test_push_reaches_only_my_devices_and_carries_no_secrets(db_session, world, vapid):
    _subscribe(db_session, world, "editor", "author")
    response = _sign_in(world, "editor").post(f"{API}/test")
    assert response.status_code == 202 and response.json() == {"devices": 1}
    assert _reached(world) == {"editor"}
    [(_, payload)] = world.pushes
    assert set(payload) <= {"title", "body", "url", "tag", "badge"}
    assert payload["url"].startswith("/") and payload["tag"] == "push-test"
    assert vapid.private not in json.dumps(payload) and vapid.private not in _sign_in(world, "editor").get(API).text


# ── the sender ──────────────────────────────────────────────────────────────────────


def _browser_keys() -> dict:
    """A real browser-side key pair (what PushManager.subscribe hands out), so pywebpush can encrypt to it."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    return {"p256dh": b64(point), "auth": b64(os.urandom(16))}


def test_sender_prunes_gone_devices_and_counts_failures_through_pywebpush(db_session, world, vapid, monkeypatch):
    """The real pywebpush (encryption, VAPID signature) with the HTTP post stubbed: 201 sends, 410 prunes,
    500 counts a failure; the next success resets the count."""
    import requests

    from marvin.db.models.users.push_subscriptions import PushSubscriptionModel
    from marvin.db.models.users.users import Users

    monkeypatch.setattr(web_push, "_post", REAL_POST)  # the world captures pushes before pywebpush; not here
    user = db_session.get(Users, world.users["editor"])
    for n in (1, 2, 3):
        keys = _browser_keys()
        web_push.subscribe(
            db_session, user, endpoint=f"https://push.example.test/editor/{n}", p256dh=keys["p256dh"], auth=keys["auth"], user_agent=None, label=None
        )
    status = {"https://push.example.test/editor/1": 201, "https://push.example.test/editor/2": 410, "https://push.example.test/editor/3": 500}
    posts: list[dict] = []

    def fake_post(url, data=None, headers=None, timeout=None, **kwargs):
        posts.append({"url": url, "headers": dict(headers or {}), "timeout": timeout, "size": len(data or b"")})
        return SimpleNamespace(status_code=status[url], reason="", text="", headers={})

    monkeypatch.setattr(requests, "post", fake_post)
    result = web_push.send_to_users(
        db_session, [user.id], web_push.ACTIVITY, web_push.PushMessage(title="Hi", body="There", url="/x", urgency="high")
    )
    assert (result.devices, result.sent, result.removed, result.failed) == (3, 1, 1, 1)
    headers = {k.lower(): v for k, v in posts[0]["headers"].items()}
    assert headers["authorization"].startswith("vapid t=") and headers["urgency"] == "high" and str(headers["ttl"]) == str(web_push.TTL_S)
    assert headers["content-encoding"] == "aes128gcm" and posts[0]["timeout"] == web_push.TIMEOUT_S
    assert all(vapid.private not in json.dumps(p["headers"]) for p in posts)

    left = {d.endpoint: d for d in web_push.devices(db_session, user.id)}
    assert set(left) == {"https://push.example.test/editor/1", "https://push.example.test/editor/3"}
    assert left["https://push.example.test/editor/3"].failure_count == 1 and left["https://push.example.test/editor/1"].failure_count == 0
    assert left["https://push.example.test/editor/1"].last_success_at is not None

    status["https://push.example.test/editor/3"] = 201
    web_push.send_to_users(db_session, [user.id], web_push.ACTIVITY, web_push.PushMessage(title="Again"))
    db_session.expire_all()
    assert db_session.query(PushSubscriptionModel).filter_by(endpoint="https://push.example.test/editor/3").one().failure_count == 0


def test_the_payload_is_small_and_links_only_inside_the_app():
    long = web_push.PushMessage(title="T" * 500, body="b " * 500, url="https://evil.example/x", tag="t" * 200, badge=3)
    payload = json.loads(long.payload())
    assert set(payload) == {"title", "body", "url", "tag", "badge"}
    assert len(payload["title"]) <= web_push.MAX_TITLE and len(payload["body"]) <= web_push.MAX_BODY and len(payload["tag"]) <= web_push.MAX_TAG
    assert payload["url"] == "/"
    for url, expected in (
        ("//evil.example", "/"),
        ("/\\evil", "/"),
        ("javascript:alert(1)", "/"),
        ("/workspace/entries/1?x=1#y", "/workspace/entries/1?x=1#y"),
    ):
        assert web_push.safe_path(url) == expected, url
    assert len(long.payload().encode()) < 1024


# ── sources: AI approvals and the bell's to-dos ─────────────────────────────────────


def _dispatch(world, event_type, data, *, message="", user_id=None, entity_id=None, entity_type=None, group_id=None):
    EventBusService(bg_tasks=None).dispatch(
        integration_id=SOURCE,
        group_id=group_id or world.gid,
        event_type=event_type,
        document_data=data,
        message=message,
        user_id=user_id,
        entity_id=entity_id,
        entity_type=entity_type,
    )


def _approval(world, owner: str):
    thread = uuid.uuid4()
    _dispatch(
        world,
        EventTypes.approval_requested,
        EventAIApprovalData(
            agent_slug="marvin",
            thread_id=thread,
            workspace_id=world.gid,
            calls=[{"id": "c1", "tool": "create_entry", "arguments": {"title": "Secret plans"}}],
        ),
        message="Marvin is waiting for your approval: create_entry",
        user_id=world.users[owner],
        entity_id=thread,
        entity_type="ai_thread",
    )
    return thread


def test_an_ai_approval_goes_to_the_runs_owner_only(db_session, world, vapid):
    _subscribe(db_session, world, *ROLES)
    thread = _approval(world, "editor")
    assert _reached(world) == {"editor"}
    [(_, payload)] = world.pushes
    assert payload["url"] == f"/workspace/settings/ai-ask?thread={thread}" and payload["tag"] == f"approval:{thread}"
    assert "Secret plans" not in json.dumps(payload)  # never the tool call's arguments

    world.pushes.clear()
    _prefer(db_session, world, "editor", approvals=False)
    _approval(world, "editor")
    assert world.pushes == []


def _submission(world, *, flagged=False):
    entry = uuid.uuid4()
    _dispatch(
        world,
        EventTypes.form_submission_received,
        EventFormSubmissionData(
            operation=EventOperation.create,
            form_id=uuid.uuid4(),
            form_name="Contact",
            submission_id=entry,
            submission_data={"email": "visitor@example.test", "message": "my phone number is 555-0100"},
            workspace_id=world.gid,
            workspace_name="Shop",
            flagged=flagged,
        ),
        message="Submission received for 'Contact'",
        entity_id=entry,
        entity_type="entry",
    )
    return entry


def test_a_form_submission_goes_to_editors_and_above_without_its_content(db_session, world, vapid):
    _subscribe(db_session, world, *ROLES, "outsider", "super1")
    entry = _submission(world)
    assert _reached(world) == {"owner", "admin", "editor"}
    payload = world.pushes[0][1]
    assert payload["url"] == f"/workspace/entries/{entry}" and payload["title"] == "Form submission · Shop"
    assert "555-0100" not in json.dumps(world.pushes) and "visitor@example.test" not in json.dumps(world.pushes)

    world.pushes.clear()
    _submission(world, flagged=True)  # suspected spam doesn't wake anyone
    assert world.pushes == []

    _prefer(db_session, world, "admin", activity=False)
    _submission(world)
    assert _reached(world) == {"owner", "editor"}


def test_a_waiting_scheduled_publish_skips_whoever_caused_it(db_session, world, vapid):
    _subscribe(db_session, world, *ROLES)
    entry = uuid.uuid4()
    _dispatch(
        world,
        EventTypes.entry_scheduled_publish_blocked,
        EventScheduledPublishBlockedData(
            entry_id=entry, entry_title="Spring sale", workspace_id=world.gid, waiting_for="approval", reason="Waiting for approval"
        ),
        message="Scheduled publish of 'Spring sale' is waiting for approval",
        user_id=world.users["editor"],
        entity_id=entry,
        entity_type="entry",
    )
    assert _reached(world) == {"owner", "admin"}


def test_another_workspaces_event_reaches_no_one_here(db_session, world, vapid):
    _subscribe(db_session, world, *ROLES)
    event = SimpleNamespace(event_type=EventTypes.approval_requested, workspace_id=world.other, user_id=world.users["editor"])
    assert not push_notifications.wants(world.gid, event)
    assert not push_notifications.wants(None, event)


# ── the Push channel: workspace notifications and platform alerts ───────────────────


def _workflow(world, ok: bool):
    EventBusService(bg_tasks=None).dispatch(
        integration_id=SOURCE,
        group_id=world.gid,
        event_type=EventTypes.automation_ran if ok else EventTypes.automation_failed,
        document_data=EventAutomationData(
            automation_id=WORKFLOW_ID,
            automation_slug="nightly-sync",
            automation_name="Nightly sync",
            ok=ok,
            error=None if ok else "step 2: 500",
            workspace_id=world.gid,
        ),
        message=f"Automation 'Nightly sync' {'ran' if ok else 'failed'}",
        entity_id=WORKFLOW_ID,
        entity_type="automation",
    )


def test_workspace_notifications_push_to_owners_and_admins_once_per_incident(db_session, world, vapid):
    _subscribe(db_session, world, *ROLES, "super1")
    assert notes.channels_for(db_session, world.gid, "workflow_failed") == ["email", "push"]

    _workflow(world, ok=False)
    assert _reached(world) == {"owner", "admin"}
    payload = world.pushes[0][1]
    assert payload["title"] == "Workflow failed: Nightly sync" and payload["url"] == f"/automation/workflows?workflow={WORKFLOW_ID}"
    status = notes.alerting.statuses(notes.WorkspaceScope(world.gid), db_session)["push"]
    assert status["outcome"] == "sent" and "2 device(s) of 2 person(s)" in status["detail"]

    world.pushes.clear()
    _workflow(world, ok=False)  # still failing: it already alerted
    assert world.pushes == []
    _workflow(world, ok=True)  # works again: one note, to the channels the alert went through
    assert _reached(world) == {"owner", "admin"} and world.pushes[0][1]["title"].startswith("Workflow working again")


def test_workspace_push_respects_its_kinds_switch_and_peoples_preferences(db_session, world, vapid):
    _subscribe(db_session, world, "owner", "admin")
    scope = notes.WorkspaceScope(world.gid)
    _save(db_session, scope, push={"enabled": True, "kinds": ["scheduled_task_failed"]})
    _workflow(world, ok=False)
    assert world.pushes == []  # push doesn't take workflow failures

    db_session.query(notes_incident()).filter_by(group_id=world.gid).delete()
    db_session.commit()
    _save(db_session, scope, push={"enabled": False, "kinds": None})
    _workflow(world, ok=False)
    assert world.pushes == []

    db_session.query(notes_incident()).filter_by(group_id=world.gid).delete()
    db_session.commit()
    _save(db_session, scope, push={"enabled": True, "kinds": None})
    _prefer(db_session, world, "admin", workspace_alerts=False)
    _workflow(world, ok=False)
    assert _reached(world) == {"owner"}


def notes_incident():
    from marvin.db.models.groups.alert_incidents import WorkspaceAlertIncidentModel

    return WorkspaceAlertIncidentModel


def _save(db_session, scope, **changes):
    current = alerting.load(scope, db_session)
    settings = alerting.validate(
        scope,
        db_session,
        types=current.types,
        email_enabled=current.email_enabled,
        recipients=current.recipients,
        email_kinds=current.email_kinds,
        routes=[r.as_stored() for r in current.routes],
        **changes,
    )
    alerting.save(scope, db_session, settings)


def test_workspace_notifications_api_shows_and_saves_push(db_session, world, vapid):
    _subscribe(db_session, world, "owner")
    client = _sign_in(world, "owner")
    body = client.get("/api/groups/notifications").json()
    assert body["push"]["configured"] is True and body["push"]["enabled"] is True and body["push"]["people"] == ["Owner Person"]

    update = {"types": {}, "email": {"enabled": True, "recipients": None, "kinds": None}, "routes": []}
    saved = client.put("/api/groups/notifications", json={**update, "push": {"enabled": False, "kinds": ["workflow_failed"]}}).json()
    assert saved["push"]["enabled"] is False and saved["push"]["kinds"] == ["workflow_failed"]
    kept = client.put("/api/groups/notifications", json=update).json()  # no push: left as it was
    assert kept["push"]["enabled"] is False and kept["push"]["kinds"] == ["workflow_failed"]

    test = client.post("/api/groups/notifications/test", json={"channel": "push"}).json()
    assert test["delivery"]["outcome"] == "sent" and _reached(world) == {"owner"}


def _backup_failed():
    EventBusService(bg_tasks=None).dispatch(
        integration_id=SOURCE,
        group_id=None,
        event_type=EventTypes.backup_failed,
        document_data=EventBackupData(
            operation=EventOperation.info, target_name="r2", target_type="s3", status="failed", reason="failed", error_message="disk full"
        ),
        message="Backup r2: failed",
    )


def test_platform_alerts_push_to_super_admins_only(db_session, world, vapid):
    _subscribe(db_session, world, "super1", "super2", "owner")
    _prefer(db_session, world, "super2", platform_alerts=False)
    _backup_failed()
    assert _reached(world) == {"super1"}
    assert world.pushes[0][1]["url"].startswith("/admin")

    client = _sign_in(world, "super1")
    body = client.get("/api/admin/alerts").json()
    assert body["push"]["configured"] is True and body["push"]["enabled"] is True and body["push"]["people"] == ["Super1 Person"]
    assert body["push"]["lastDelivery"]["outcome"] == "sent"
    saved = client.put(
        "/api/admin/alerts", json={"types": {}, "email": {"enabled": True, "recipients": None}, "routes": [], "push": {"enabled": False}}
    )
    assert saved.json()["push"]["enabled"] is False
    world.pushes.clear()
    _backup_failed()
    assert world.pushes == []


def test_platform_alerts_are_unchanged_without_push(db_session, world):
    _subscribe(db_session, world, "super1")
    _backup_failed()
    assert world.pushes == []
    assert "push" not in platform.statuses(db_session)
    assert platform.load(db_session).channels_for("backup_failed") == ["email"]


def test_a_users_devices_go_with_them(db_session, world, vapid):
    from marvin.db.models.users.push_subscriptions import PushSubscriptionModel
    from marvin.db.models.users.users import Users

    _subscribe(db_session, world, "viewer")
    db_session.delete(db_session.get(Users, world.users["viewer"]))
    db_session.commit()
    assert db_session.query(PushSubscriptionModel).filter_by(user_id=world.users["viewer"]).count() == 0


def test_the_vapid_script_prints_a_usable_key_pair(capsys):
    from py_vapid import Vapid

    from marvin.scripts import vapid as script

    assert script.main(["--subject", "mailto:ops@example.test"]) == 0
    env = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    assert set(env) == {"VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"} and env["VAPID_SUBJECT"] == "mailto:ops@example.test"
    assert len(base64.urlsafe_b64decode(env["VAPID_PUBLIC_KEY"] + "==")) == 65
    assert Vapid.from_string(private_key=env["VAPID_PRIVATE_KEY"]).public_key is not None
    with pytest.raises(SystemExit):
        script.main(["--subject", "ops@example.test"])
