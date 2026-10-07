"""Platform alerts past the bell (Admin → Platform alerts, services/platform_alerts.py).

Platform events (backups, storage, security) reach super admins by email — built in, on by default — and
through any message-capable integration action on a connection in the platform workspace. The actions
are found from provider metadata (the ``notify`` capability or category), never by name. One dispatched
event is one attempt per enabled channel; a failing channel is recorded and never stops the others.
Nothing here sends real email or chat: the providers are fakes and the SMTP send is captured.
"""

import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from fastapi.testclient import TestClient  # noqa: E402
from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.app import app  # noqa: E402
from marvin.core.dependencies import get_current_user  # noqa: E402
from marvin.db.models.users.roles import PlatformRole  # noqa: E402
from marvin.services import platform_alerts as alerts  # noqa: E402
from marvin.services.event_bus_service.event_bus_service import EventBusService  # noqa: E402
from marvin.services.event_bus_service.event_types import EventBackupData, EventOperation, EventTypes  # noqa: E402
from marvin.services.integrations import alert_routing  # noqa: E402

API = "/api/admin/alerts"
SOURCE = "test_platform_alerts"
FAKE_TOKEN = "fake-token-not-real-0000"


# ── fake providers ─────────────────────────────────────────────────────────────


class _Chat(IntegrationProvider):
    """A chat plugin: notify category, a message action that also needs a channel."""

    slug = "test_chat"
    name = "Test Chat"
    category = "notify"
    actions = (
        ProviderAction(
            key="post",
            label="Post message",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}, "channel": {"type": "string", "title": "Channel"}},
                "required": ["text", "channel"],
            },
        ),
        ProviderAction(key="list_channels", label="List channels"),  # no body field: not a message action
    )
    calls: list = []
    fail_with: Exception | None = None

    def run_action(self, key, args, ctx):
        type(self).calls.append(SimpleNamespace(key=key, args=dict(args), secret=ctx.secret))
        if type(self).fail_with is not None:
            raise type(self).fail_with
        return {"ok": True}


class _Pager(IntegrationProvider):
    """Not a notify plugin, but one action declares the ``notify`` capability (title + body)."""

    slug = "test_pager"
    name = "Test Pager"
    category = "destination"
    actions = (
        ProviderAction(
            key="page",
            label="Page on-call",
            capability="notify",
            input_schema={"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}, "required": ["body"]},
        ),
    )
    calls: list = []

    def run_action(self, key, args, ctx):
        type(self).calls.append(SimpleNamespace(key=key, args=dict(args)))
        return {}


class _Deploy(IntegrationProvider):
    """A destination with a text input: it must never be offered as an alert route."""

    slug = "test_deploy"
    name = "Test Deploy"
    category = "destination"
    actions = (ProviderAction(key="deploy", label="Deploy", input_schema={"type": "object", "properties": {"text": {"type": "string"}}}),)

    def run_action(self, key, args, ctx):
        raise AssertionError("a deploy hook must never carry an alert")


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    for cls in (_Chat, _Pager, _Deploy):
        monkeypatch.setitem(INTEGRATION_REGISTRY, cls.slug, cls())
    _Chat.calls, _Chat.fail_with, _Pager.calls = [], None, []
    yield


# ── world ─────────────────────────────────────────────────────────────────────


def _clear_settings(session):
    from marvin.db.models.platform.platform_settings import PlatformSettingsModel

    session.query(PlatformSettingsModel).filter(PlatformSettingsModel.key.in_([alerts.SETTINGS_KEY, alerts.STATUS_KEY])).delete(
        synchronize_session=False
    )
    session.commit()


@pytest.fixture
def world(db_session, monkeypatch):
    """A platform workspace with chat, pager and deploy connections, another workspace with a chat
    connection, two super admins and one ordinary user."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.db.models.users.users import Users

    _clear_settings(db_session)
    gid, other = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    groups = {}
    for key, g_id in (("platform", gid), ("other", other)):
        group = Groups(session=db_session, name=f"pa-{key}-{marker}", slug=f"pa-{key}-{marker}")
        group.id = g_id
        db_session.add(group)
        groups[key] = group
    db_session.flush()

    def connection(group_id, provider, name, enabled=True):
        row = IntegrationModel(
            session=db_session, group_id=group_id, provider=provider, name=name, slug=f"{name.lower()}-{marker}", enabled=enabled, config={}
        )
        db_session.add(row)
        return row

    chat = connection(gid, "test_chat", "Ops")
    pager = connection(gid, "test_pager", "Oncall")
    deploy = connection(gid, "test_deploy", "Site")
    foreign = connection(other, "test_chat", "Elsewhere")
    users = {}
    for name, role in (("ada", "SUPER_ADMIN"), ("bob", "SUPER_ADMIN"), ("cy", "NONE")):
        uid = uuid.uuid4()
        users[name] = uid
        db_session.execute(
            sa.insert(Users.__table__).values(
                id=uid,
                group_id=gid,
                full_name=f"{name.title()} Person",
                username=f"{name}-{marker}",
                email=f"{name}-{marker}@example.test",
                auth_method="MARVIN",
                is_superuser=False,
                platform_role=role,
                admin=False,
            )
        )
    db_session.commit()
    monkeypatch.setattr(alerts, "_platform_workspace", lambda session: session.get(Groups, gid))

    sent: list = []  # (to, subject, html) — the captured SMTP sends
    monkeypatch.setattr(alerts, "smtp_ready", lambda: True)
    monkeypatch.setattr(
        "marvin.services.email.email_service.EmailService.send_email",
        lambda self, to, template: sent.append((to, template.subject, template.message_top + template.message_bottom)) or True,
    )
    yield SimpleNamespace(
        gid=gid,
        other=other,
        marker=marker,
        chat=chat,
        pager=pager,
        deploy=deploy,
        foreign=foreign,
        users=users,
        emails={n: f"{n}-{marker}@example.test" for n in users},
        sent=sent,
    )

    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    _clear_settings(db_session)
    db_session.query(EventLogModel).filter(EventLogModel.integration_id.in_([SOURCE, "platform_settings"])).delete(synchronize_session=False)
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id.in_([gid, other])).delete(synchronize_session=False)
    db_session.query(Users).filter(Users.id.in_(list(users.values()))).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.id.in_([gid, other])).delete(synchronize_session=False)
    db_session.commit()


def _admin(world, role=PlatformRole.SUPER_ADMIN) -> TestClient:
    user = SimpleNamespace(
        id=world.users["ada"],
        group_id=world.gid,
        active_group_id=world.gid,
        platform_role=role,
        is_superuser=False,
        admin=True,
        full_name="Ada Person",
        username=f"ada-{world.marker}",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _configure(db_session, world, *, routes=(), recipients=None, email=True, types=None):
    settings = alerts.validate(db_session, types=types or {}, email_enabled=email, recipients=recipients, routes=list(routes))
    alerts.save(db_session, settings)
    return alerts.load(db_session)


def _chat_route(world, channel="#ops", enabled=True):
    return {"integration_id": str(world.chat.id), "action": "post", "args": {"channel": channel}, "enabled": enabled}


def _backup(reason: str, status: str = "failed", error: str | None = "disk full", target: str = "r2"):
    """Dispatch a backup event through the real bus, the way the backup health check does."""
    event_type = EventTypes.backup_completed if reason in ("completed", "recovered") else EventTypes.backup_failed
    EventBusService(bg_tasks=None).dispatch(
        integration_id=SOURCE,
        group_id=None,
        event_type=event_type,
        document_data=EventBackupData(
            operation=EventOperation.info, target_name=target, target_type="s3", status=status, reason=reason, error_message=error
        ),
        message=f"Backup {target}: {reason}",
    )


# ── discovery ─────────────────────────────────────────────────────────────────


def test_message_actions_come_from_provider_metadata_not_names():
    chat = alert_routing.message_actions(INTEGRATION_REGISTRY["test_chat"])
    assert [(a.key, a.body_field, a.title_field, a.required) for a in chat] == [("post", "text", None, ("channel",))]
    assert list(chat[0].inputs) == ["channel"]
    pager = alert_routing.message_actions(INTEGRATION_REGISTRY["test_pager"])
    assert [(a.key, a.body_field, a.title_field) for a in pager] == [("page", "body", "title")]
    assert alert_routing.message_actions(INTEGRATION_REGISTRY["test_deploy"]) == []


def test_message_args_keep_the_workspace_alert_shapes():
    """Slack-shaped (one text) and Apprise-shaped (title + body) actions get exactly the args the workspace
    alert routing always wrote."""

    class Slackish(IntegrationProvider):
        slug, name, category = "x_slackish", "Slackish", "notify"
        actions = (ProviderAction(key="send_message", label="Send", input_schema={"type": "object", "properties": {"text": {"type": "string"}}}),)

    class Apprisish(IntegrationProvider):
        slug, name, category = "x_apprisish", "Apprisish", "notify"
        actions = (
            ProviderAction(
                key="notify",
                label="Notify",
                capability="notify",
                input_schema={"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}},
            ),
        )

    (slack,) = alert_routing.message_actions(Slackish())
    (apprise,) = alert_routing.message_actions(Apprisish())
    assert alert_routing._template_args(slack) == {"text": "*{{title}}*\n{{summary}}"}
    assert alert_routing._template_args(apprise) == {"title": "{{title}}", "body": "{{summary}}"}


def test_workspace_routing_skips_actions_that_need_more_than_the_message():
    assert alert_routing._notify_action("test_chat") is None  # needs a channel the workspace panel can't give
    assert alert_routing._notify_action("test_pager").key == "page"
    assert alert_routing._notify_action("test_deploy") is None
    assert alert_routing._notify_action("not_installed") is None


def test_targets_are_the_platform_workspace_message_actions(db_session, world):
    found = {(t.integration_name, t.action.key) for t in alerts.targets(db_session, alerts._platform_workspace(db_session))}
    assert found == {("Ops", "post"), ("Oncall", "page")}  # not the deploy hook, not another workspace's chat


def test_the_platform_workspace_is_found_in_one_place(db_session):
    """Without the test's stand-in, ``_platform_workspace`` is the marked platform workspace, whatever its name."""
    from marvin.db.models.groups import Groups
    from marvin.services.group.platform_workspace import PlatformWorkspaceMissing, platform_workspace

    created = None
    try:
        marked = platform_workspace(db_session)
    except PlatformWorkspaceMissing:
        name = f"Not-Default-{uuid.uuid4().hex[:6]}"
        marked = created = Groups(session=db_session, name=name, slug=name.lower(), is_platform=True)
        db_session.add(created)
        db_session.commit()
    try:
        assert alerts._platform_workspace(db_session).id == marked.id
    finally:
        if created is not None:
            db_session.delete(created)
            db_session.commit()


# ── which events alert ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("event_type", "reason", "kind"),
    [
        ("backup_failed", "failed", "backup_failed"),
        ("backup_failed", "partial", "backup_failed"),
        ("backup_failed", "overdue", "backup_overdue"),
        ("backup_completed", "recovered", "backup_recovered"),
        ("backup_completed", "completed", None),  # routine successful runs never alert
        ("storage_provider_changed", None, "storage_provider_changed"),
        ("storage_public_domain_changed", None, None),  # off by default
        ("login_failed_multiple_times", None, "login_failed_multiple_times"),
        ("user_signup", None, None),  # not an alert kind
    ],
)
def test_default_routing_per_type(db_session, world, event_type, reason, kind):
    settings = alerts.load(db_session)
    found = settings.enabled_kind(event_type, {"reason": reason} if reason else {})
    assert (found.key if found else None) == kind


def test_a_kind_turned_off_does_not_alert(db_session, world):
    settings = _configure(db_session, world, types={"backup_overdue": False, "storage_public_domain_changed": True}, recipients=[world.emails["ada"]])
    assert settings.enabled_kind("backup_failed", {"reason": "overdue"}) is None
    assert settings.enabled_kind("storage_public_domain_changed", {}).key == "storage_public_domain_changed"
    _backup("overdue", status="missed")
    assert world.sent == []


# ── email ─────────────────────────────────────────────────────────────────────


def test_email_goes_to_every_super_admin_by_default(db_session, world):
    defaults = alerts.super_admin_emails(db_session)
    assert {world.emails["ada"], world.emails["bob"]} <= set(defaults)
    assert world.emails["cy"] not in defaults

    _backup("failed")
    to = {addr for addr, *_ in world.sent}
    assert to == set(defaults)
    subject, body = world.sent[0][1], world.sent[0][2]
    assert subject == "Backup Failed"
    assert "Backup r2: failed" in body and "disk full" in body and alerts.SCOPE in body


def test_email_without_smtp_is_recorded_not_sent(db_session, world, monkeypatch):
    monkeypatch.setattr(alerts, "smtp_ready", lambda: False)
    _backup("failed")
    assert world.sent == []
    status = alerts.statuses(db_session)[alerts.EMAIL_CHANNEL]
    assert status["outcome"] == "skipped" and "SMTP" in status["detail"] and status["event_type"] == "backup_failed"


# ── integration routes ──────────────────────────────────────────────────────────


def test_one_event_is_delivered_once_to_each_enabled_channel(db_session, world):
    _configure(
        db_session,
        world,
        recipients=[world.emails["ada"]],
        routes=[_chat_route(world), {"integration_id": str(world.pager.id), "action": "page", "args": {}, "enabled": True}],
    )
    _backup("failed")
    assert len(world.sent) == 1
    assert [c.key for c in _Chat.calls] == ["post"]
    assert [c.key for c in _Pager.calls] == ["page"]
    (chat,) = _Chat.calls
    assert chat.args["channel"] == "#ops"
    assert chat.args["text"].startswith("*Backup Failed*\nBackup r2: failed")
    assert _Pager.calls[0].args["title"] == "Backup Failed" and "Scope: Platform — all workspaces" in _Pager.calls[0].args["body"]
    assert "/admin/backup-health" in _Pager.calls[0].args["body"]


def test_a_disabled_route_is_skipped(db_session, world):
    _configure(db_session, world, email=False, routes=[_chat_route(world, enabled=False)])
    _backup("failed")
    assert _Chat.calls == [] and world.sent == []


def test_a_failing_route_never_stops_the_others(db_session, world, monkeypatch):
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, group_id: FAKE_TOKEN)
    world.chat.secret_ref = "OPS_TOKEN"
    db_session.commit()
    _Chat.fail_with = ValueError(f"401 from chat: bad token {FAKE_TOKEN}")
    settings = _configure(
        db_session,
        world,
        recipients=[world.emails["ada"]],
        routes=[_chat_route(world), {"integration_id": str(world.pager.id), "action": "page", "args": {}, "enabled": True}],
    )
    _backup("failed")
    assert len(_Chat.calls) == 1  # one attempt, no retry
    assert len(_Pager.calls) == 1 and len(world.sent) == 1
    status = alerts.statuses(db_session)
    chat_id, pager_id = (r.id for r in settings.routes)
    assert status[chat_id]["outcome"] == "failed" and "401 from chat" in status[chat_id]["detail"]
    assert FAKE_TOKEN not in status[chat_id]["detail"]  # the connection's credential is redacted
    assert status[pager_id]["outcome"] == "sent" and status[alerts.EMAIL_CHANNEL]["outcome"] == "sent"


def test_messages_carry_no_secrets(db_session, world, monkeypatch):
    monkeypatch.setenv("BACKUP_S3_SECRET_ACCESS_KEY", "fake-secret-value-123")
    _configure(db_session, world, recipients=[world.emails["ada"]], routes=[_chat_route(world)])
    _backup("failed", error="upload to s3://keyid:hunter2@bucket.example failed: signature fake-secret-value-123 rejected")
    text = _Chat.calls[0].args["text"]
    assert "hunter2" not in text and "fake-secret-value-123" not in text and "s3://****@bucket.example" in text
    assert "hunter2" not in world.sent[0][2] and "fake-secret-value-123" not in world.sent[0][2]


def test_a_route_through_a_connection_that_is_gone_reports_it(db_session, world):
    settings = _configure(db_session, world, email=False, routes=[_chat_route(world)])
    world.chat.enabled = False
    db_session.commit()
    _backup("failed")
    assert _Chat.calls == []
    status = alerts.statuses(db_session)[settings.routes[0].id]
    assert status["outcome"] == "failed" and "turned off" in status["detail"]


# ── admin API ─────────────────────────────────────────────────────────────────


def test_admin_api_lists_kinds_email_and_targets(db_session, world):
    res = _admin(world).get(API)
    assert res.status_code == 200, res.text
    body = res.json()
    assert {t["key"]: t["enabled"] for t in body["types"]}["storage_public_domain_changed"] is False
    assert body["email"]["enabled"] is True and body["email"]["recipients"] is None
    assert {world.emails["ada"], world.emails["bob"]} <= set(body["email"]["superAdminEmails"])
    assert body["platformWorkspace"]["id"] == str(world.gid)
    targets = {(t["integrationName"], t["action"]): t for t in body["targets"]}
    assert set(targets) == {("Ops", "post"), ("Oncall", "page")}
    assert targets[("Ops", "post")]["inputs"] == [{"key": "channel", "label": "Channel", "description": "", "required": True}]


def test_admin_api_saves_routes_and_audits_the_change(db_session, world):
    from marvin.db.models.platform.event_log import EventLogModel

    client = _admin(world)
    res = client.put(
        API,
        json={
            "types": {"backup_recovered": False},  # kind keys, as listed
            "email": {"enabled": True, "recipients": [world.emails["bob"]]},
            "routes": [{"integrationId": str(world.chat.id), "action": "post", "args": {"channel": "#very-private-ops"}, "enabled": True}],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    (route,) = body["routes"]
    assert route["label"] == "Ops → Post message" and route["args"] == {"channel": "#very-private-ops"} and route["problem"] is None
    assert body["email"]["recipients"] == [world.emails["bob"]]

    db_session.expire_all()
    (row,) = (
        db_session.query(EventLogModel)
        .filter(EventLogModel.event_type == "platform_settings_changed", EventLogModel.integration_id == "platform_settings")
        .all()
    )
    assert row.workspace_id is None
    changes = row.event_data["documentData"]["changes"]
    assert "Backup recovered: off" in changes and "Route added: Ops → Post message" in changes and "Email recipients: 1 address(es)" in changes
    assert "very-private" not in str(row.event_data)  # arguments are named, never shown

    from marvin.services.events.event_catalog import get_catalog_entry, is_platform_event

    assert is_platform_event("platform_settings_changed") and get_catalog_entry("platform_settings_changed").audit_locked

    # saving the same thing again keeps the route's id and audits nothing
    again = client.put(
        API,
        json={
            "types": {"backup_recovered": False},
            "email": {"enabled": True, "recipients": [world.emails["bob"]]},
            "routes": [{"id": route["id"], "integrationId": str(world.chat.id), "action": "post", "args": {"channel": "#very-private-ops"}}],
        },
    )
    assert again.status_code == 200 and again.json()["routes"][0]["id"] == route["id"]
    db_session.expire_all()
    assert (
        db_session.query(EventLogModel)
        .filter(EventLogModel.event_type == "platform_settings_changed", EventLogModel.integration_id == "platform_settings")
        .count()
        == 1
    )


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"types": {"nope": True}}, "Unknown alert type"),
        ({"email": {"enabled": True, "recipients": ["not-an-email"]}}, "isn't an email address"),
        ({"email": {"enabled": True, "recipients": []}}, "at least one"),
        ({"routes": [{"integrationId": "FOREIGN", "action": "post", "args": {"channel": "#x"}}]}, "can't carry alerts"),
        ({"routes": [{"integrationId": "DEPLOY", "action": "deploy"}]}, "can't carry alerts"),
        ({"routes": [{"integrationId": "CHAT", "action": "post", "args": {}}]}, "needs channel"),
        ({"routes": [{"integrationId": "CHAT", "action": "post", "args": {"channel": "#x", "colour": "red"}}]}, "takes no 'colour'"),
    ],
)
def test_admin_api_refuses_what_cannot_work(db_session, world, payload, detail):
    ids = {"FOREIGN": str(world.foreign.id), "DEPLOY": str(world.deploy.id), "CHAT": str(world.chat.id)}
    for route in payload.get("routes", []):
        route["integrationId"] = ids[route["integrationId"]]
    res = _admin(world).put(API, json=payload)
    assert res.status_code == 422 and detail in res.text, res.text


def test_one_action_can_serve_two_channels_but_not_the_same_one_twice(db_session, world):
    settings = _configure(db_session, world, recipients=[world.emails["ada"]], routes=[_chat_route(world, "#ops"), _chat_route(world, "#oncall")])
    assert [r.args["channel"] for r in settings.routes] == ["#ops", "#oncall"]
    _backup("failed")
    assert sorted(c.args["channel"] for c in _Chat.calls) == ["#oncall", "#ops"]
    with pytest.raises(alerts.InvalidAlertSettings, match="listed twice"):
        _configure(db_session, world, routes=[_chat_route(world, "#ops"), _chat_route(world, "#ops")])


def test_admin_api_is_super_admin_only(world):
    assert _admin(world, PlatformRole.NONE).get(API).status_code == 403


def test_test_button_sends_the_test_message_through_one_channel(db_session, world):
    settings = _configure(db_session, world, email=False, recipients=[world.emails["ada"]], routes=[_chat_route(world, enabled=False)])
    client = _admin(world)

    res = client.post(f"{API}/test", json={"channel": "email"})  # off, but a test still goes
    assert res.status_code == 200, res.text
    assert res.json()["delivery"]["outcome"] == "sent" and res.json()["delivery"]["test"] is True
    assert [(to, subject) for to, subject, _ in world.sent] == [(world.emails["ada"], alerts.TEST_TITLE)]

    route_id = settings.routes[0].id
    res = client.post(f"{API}/test", json={"channel": route_id})
    assert res.status_code == 200 and res.json()["delivery"]["outcome"] == "sent"
    (call,) = _Chat.calls
    assert call.args["text"].startswith(f"*{alerts.TEST_TITLE}*") and call.args["channel"] == "#ops"

    body = client.get(API).json()
    assert body["routes"][0]["lastDelivery"]["test"] is True and body["email"]["lastDelivery"]["outcome"] == "sent"
    assert client.post(f"{API}/test", json={"channel": "no-such-route"}).status_code == 404


def test_without_a_platform_workspace_routes_are_unavailable_and_email_still_works(db_session, world, monkeypatch):
    _configure(db_session, world, recipients=[world.emails["ada"]], routes=[_chat_route(world)])
    monkeypatch.setattr(alerts, "_platform_workspace", lambda session: None)
    body = _admin(world).get(API).json()
    assert body["platformWorkspace"] is None and body["targets"] == []
    assert "no platform workspace" in body["routes"][0]["problem"]
    res = _admin(world).put(API, json={"routes": [{"integrationId": str(world.chat.id), "action": "post", "args": {"channel": "#x"}}]})
    assert res.status_code == 422

    _backup("failed")
    assert len(world.sent) == 1 and _Chat.calls == []
