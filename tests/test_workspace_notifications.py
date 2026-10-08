"""A workspace's notifications past the bell (Settings → Automation → Notifications, services/workspace_alerts.py).

The workspace's own failures — a workflow, a scheduled task, a connection that needs attention, and (off by
default) AI operations and webhook deliveries — reach its owners and admins by email (built in, on by default)
and any message-capable action on one of its connections, each channel taking every kind or only some. A
workflow or scheduled task that keeps failing alerts once and says when it works again; integration alerts
keep their own incident and reminders and resolve back through the channels they went out through. Platform
events never reach it. The settings, channels and message are services/alerting.py's, shared with platform
alerts (tests/test_platform_alerts.py). Nothing here sends real email or chat.
"""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services import alerting
from marvin.services import workspace_alerts as notes
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import (
    EventAutomationData,
    EventBackupData,
    EventOperation,
    EventScheduledTaskData,
    EventTypes,
)

API = "/api/groups/notifications"
SOURCE = "test_workspace_notifications"
ROLES = ("owner", "admin", "editor", "author", "viewer")


# ── world ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def world(db_session, monkeypatch):
    """A workspace with one member per role (each with an email address) and another workspace; email is
    captured, never sent."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.alert_incidents import WorkspaceAlertIncidentModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.platform.event_log import EventLogModel
    from marvin.db.models.users.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    gid, other = uuid.uuid4(), uuid.uuid4()
    marker = gid.hex[:8]
    for key, g_id in (("ws", gid), ("other", other)):
        group = Groups(session=db_session, name=f"wn-{key}-{marker}", slug=f"wn-{key}-{marker}")
        group.id = g_id
        db_session.add(group)
    db_session.flush()
    for g_id in (gid, other):
        if db_session.query(GroupPreferencesModel).filter_by(group_id=g_id).first() is None:
            db_session.add(GroupPreferencesModel(session=db_session, group_id=g_id))
    users = {}
    for role in ROLES:
        uid = uuid.uuid4()
        users[role] = uid
        db_session.execute(
            sa.insert(Users.__table__).values(
                id=uid,
                group_id=gid,
                full_name=f"{role.title()} Person",
                username=f"{role}-{marker}",
                email=f"{role}-{marker}@example.test",
                password="x",
                auth_method="MARVIN",
                is_superuser=False,
                platform_role="NONE",
                admin=False,
            )
        )
        db_session.execute(
            sa.insert(WorkspaceMembers.__table__).values(id=uuid.uuid4(), user_id=uid, group_id=gid, workspace_role=WorkspaceRole[role.upper()])
        )
    db_session.commit()

    sent: list = []  # (to, subject, html) — the captured SMTP sends
    monkeypatch.setattr(notes, "smtp_ready", lambda session, group_id: True)
    monkeypatch.setattr(
        "marvin.services.email.email_service.EmailService.send_email",
        lambda self, to, template: sent.append((to, template.subject, template.message_top + template.message_bottom)) or True,
    )
    yield SimpleNamespace(gid=gid, other=other, marker=marker, users=users, emails={r: f"{r}-{marker}@example.test" for r in ROLES}, sent=sent)

    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskExecutionLogModel, ScheduledTaskModel

    for model in (WorkspaceAlertIncidentModel, IntegrationAlertModel, ScheduledTaskExecutionLogModel, ScheduledTaskModel, IntegrationModel):
        db_session.query(model).filter(model.group_id.in_([gid, other])).delete(synchronize_session=False)
    db_session.query(EventLogModel).filter(EventLogModel.workspace_id.in_([gid, other])).delete(synchronize_session=False)
    db_session.query(WorkspaceMembers).filter(WorkspaceMembers.group_id == gid).delete(synchronize_session=False)
    db_session.query(Users).filter(Users.id.in_(list(users.values()))).delete(synchronize_session=False)
    db_session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id.in_([gid, other])).delete(synchronize_session=False)
    db_session.query(Groups).filter(Groups.id.in_([gid, other])).delete(synchronize_session=False)
    db_session.commit()


def _configure(db_session, world, *, routes=(), recipients=None, email=True, email_kinds=None, types=None):
    scope = notes.WorkspaceScope(world.gid)
    settings = alerting.validate(
        scope, db_session, types=types or {}, email_enabled=email, recipients=recipients, email_kinds=email_kinds, routes=list(routes)
    )
    alerting.save(scope, db_session, settings)
    return notes.load(db_session, world.gid)


def _workflow(world, ok: bool, *, automation_id=None, name="Nightly sync", handled=False, group_id=None):
    """A workflow run's end, dispatched through the real bus the way the engine announces it."""
    automation_id = automation_id or WORKFLOW_ID
    EventBusService(bg_tasks=None).dispatch(
        integration_id=SOURCE,
        group_id=group_id or world.gid,
        event_type=EventTypes.automation_ran if ok else EventTypes.automation_failed,
        document_data=EventAutomationData(
            automation_id=automation_id,
            automation_slug=name.lower().replace(" ", "-"),
            automation_name=name,
            ok=ok,
            error=None if ok else "step 2 (webhook): 500 from the shop",
            workspace_id=group_id or world.gid,
            handled=handled,
        ),
        message=f"Automation '{name}' {'ran' if ok else 'failed'}",
        entity_id=automation_id,
        entity_type="automation",
    )


WORKFLOW_ID = uuid.UUID("00000000-0000-4000-8000-00000000a001")


def _subjects(world) -> list[str]:
    return [subject for _, subject, _ in world.sent]


# ── kinds and defaults ──────────────────────────────────────────────────────────


def test_kinds_and_their_defaults(db_session, world):
    settings = notes.load(db_session, world.gid)
    assert settings.types == {
        "workflow_failed": True,
        "scheduled_task_failed": True,
        "integration_attention": True,
        "ai_operation_failed": False,
        "webhook_delivery_failed": False,
        "trash_auto_empty_soon": False,
    }
    assert (settings.email_enabled, settings.recipients, settings.email_kinds, settings.routes) == (True, None, None, [])
    assert notes.channels_for(db_session, world.gid, "workflow_failed") == ["email"]
    assert notes.channels_for(db_session, world.gid, "ai_operation_failed") == []  # off by default


def test_email_goes_to_the_owners_and_admins_by_default(db_session, world):
    assert set(notes.admin_emails(db_session, world.gid)) == {world.emails["owner"], world.emails["admin"]}
    _workflow(world, ok=False)
    assert {to for to, *_ in world.sent} == {world.emails["owner"], world.emails["admin"]}
    subject, body = world.sent[0][1], world.sent[0][2]
    assert subject == "Workflow failed: Nightly sync"
    assert "500 from the shop" in body and "Scope: Workspace — wn-ws-" in body and "Settings → Automation → Notifications" in body


def test_an_explicit_list_replaces_them(db_session, world):
    _configure(db_session, world, recipients=["ops@example.test"])
    _workflow(world, ok=False)
    assert [to for to, *_ in world.sent] == ["ops@example.test"]


def test_without_smtp_email_is_recorded_not_sent(db_session, world, monkeypatch):
    monkeypatch.setattr(notes, "smtp_ready", lambda session, group_id: False)
    _workflow(world, ok=False)
    assert world.sent == []
    status = alerting.statuses(notes.WorkspaceScope(world.gid), db_session)["email"]
    assert status["outcome"] == "skipped" and "email isn't set up" in status["detail"] and status["event_type"] == "automation_failed"


# ── once per incident ─────────────────────────────────────────────────────────────


def test_a_workflow_that_keeps_failing_alerts_once_and_its_next_success_says_so(db_session, world):
    _configure(db_session, world, recipients=["ops@example.test"])
    _workflow(world, ok=False)
    _workflow(world, ok=False)
    _workflow(world, ok=False)
    assert _subjects(world) == ["Workflow failed: Nightly sync"]

    _workflow(world, ok=True)
    assert _subjects(world) == ["Workflow failed: Nightly sync", "Workflow working again: Nightly sync"]
    assert "succeeded after 3 failed runs since" in world.sent[1][2]

    _workflow(world, ok=True)  # routine successes say nothing
    _workflow(world, ok=False)  # a new incident alerts again
    assert _subjects(world) == ["Workflow failed: Nightly sync", "Workflow working again: Nightly sync", "Workflow failed: Nightly sync"]


def test_each_workflow_is_its_own_incident(db_session, world):
    _configure(db_session, world, recipients=["ops@example.test"])
    _workflow(world, ok=False)
    _workflow(world, ok=False, automation_id=uuid.uuid4(), name="Tag recipes")
    assert _subjects(world) == ["Workflow failed: Nightly sync", "Workflow failed: Tag recipes"]


def test_a_failure_the_integration_handled_does_not_alert(db_session, world):
    _workflow(world, ok=False, handled=True)
    _workflow(world, ok=True)
    assert world.sent == []


def test_a_kind_turned_off_neither_alerts_nor_opens_an_incident(db_session, world):
    _configure(db_session, world, types={"workflow_failed": False})
    _workflow(world, ok=False)
    _configure(db_session, world, types={"workflow_failed": True})
    _workflow(world, ok=True)
    assert world.sent == []


def test_the_working_again_note_goes_where_the_alert_went(db_session, world):
    _configure(db_session, world, recipients=["ops@example.test"])
    _workflow(world, ok=False)
    _configure(db_session, world, email=False, recipients=["ops@example.test"])  # turned off in between: the note still closes the loop
    _workflow(world, ok=True)
    assert [(to, subject) for to, subject, _ in world.sent] == [
        ("ops@example.test", "Workflow failed: Nightly sync"),
        ("ops@example.test", "Workflow working again: Nightly sync"),
    ]


def _handler(result):
    from marvin.services.scheduled_tasks.handlers import ScheduledTaskHandler

    class _Handler(ScheduledTaskHandler):
        name = "test"

        def execute(self, task, event_bus):
            if isinstance(result, Exception):
                raise result
            return result

    return _Handler


def test_a_scheduled_task_alerts_once_and_even_a_quiet_recovery_says_so(db_session, world, monkeypatch):
    """Through the real scheduled task listener: two failed runs, then a run with nothing to report."""
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
    from marvin.services.event_bus_service.event_bus_listener import ScheduledTaskListener
    from marvin.services.event_bus_service.event_types import Event, EventBusMessage
    from marvin.services.scheduled_tasks import TaskHandlerRegistry

    _configure(db_session, world, recipients=["ops@example.test"])
    task = ScheduledTaskModel(
        session=db_session,
        group_id=world.gid,
        name="Poll the inbox",
        slug=f"poll-{world.marker}",
        schedule_type="interval",
        schedule_config={"minutes": 2},
        task_type="test_notify_task",
        task_config={},
    )
    db_session.add(task)
    db_session.commit()

    def run(result):
        monkeypatch.setitem(TaskHandlerRegistry._handlers, "test_notify_task", _handler(result))
        db_session.refresh(task)
        event = Event(
            message=EventBusMessage.from_type(EventTypes.scheduled_task_triggered, body="triggered"),
            event_type=EventTypes.scheduled_task_triggered,
            integration_id="scheduled_tasks",
            document_data=EventScheduledTaskData.from_model(task),
            workspace_id=world.gid,
        )
        ScheduledTaskListener(world.gid).publish_to_subscribers(event, ["scheduled_task_handler"])

    run(RuntimeError("inbox unreachable"))
    run(RuntimeError("inbox unreachable"))
    assert _subjects(world) == ["Scheduled task failed: Poll the inbox"]
    assert "inbox unreachable" in world.sent[0][2]

    run(None)  # nothing to report — a routine run would log nothing, but this one ends the failures
    assert _subjects(world) == ["Scheduled task failed: Poll the inbox", "Scheduled task working again: Poll the inbox"]
    run(None)
    assert len(world.sent) == 2


# ── integration alerts ──────────────────────────────────────────────────────────


def _connection(db_session, world, provider="test_note_chat", name="Ops"):
    from marvin.db.models.groups.integrations import IntegrationModel

    row = IntegrationModel(
        session=db_session, group_id=world.gid, provider=provider, name=name, slug=f"{name.lower()}-{world.marker}", enabled=True, config={}
    )
    db_session.add(row)
    db_session.commit()
    return row


def _needs_attention(db_session, world, integration):
    from marvin.services.integrations import errors

    return errors.notify(
        db_session,
        world.gid,
        integration_id=integration.id,
        integration_slug=integration.slug,
        provider=integration.provider,
        code="auth",
        message="token expired",
    )


def test_integration_alerts_go_out_with_reminders_and_resolve_back_through_the_same_channels(db_session, world):
    from marvin.services.integrations import errors

    integration = _connection(db_session, world)
    _configure(db_session, world, recipients=["ops@example.test"])
    alert = _needs_attention(db_session, world, integration)
    assert alert.channels["notify"] == ["email"]
    assert _subjects(world) == ["test_note_chat needs attention"]

    _needs_attention(db_session, world, integration)  # counted on the open alert: no new message
    assert len(world.sent) == 1
    alert.notified_at = datetime.now(UTC) - timedelta(hours=25)
    db_session.commit()
    _needs_attention(db_session, world, integration)  # the reminder window passed
    assert _subjects(world) == ["test_note_chat needs attention"] * 2

    _configure(db_session, world, recipients=["ops@example.test"], email_kinds=["workflow_failed"])  # no longer takes them
    assert errors.resolve_alerts(db_session, world.gid, integration.id, resolution="manual") == 1
    assert _subjects(world)[-1] == "test_note_chat is working again"


def test_integration_alerts_with_the_kind_off_go_nowhere(db_session, world):
    integration = _connection(db_session, world)
    _configure(db_session, world, types={"integration_attention": False})
    alert = _needs_attention(db_session, world, integration)
    assert alert.channels["notify"] == []
    assert world.sent == []


# ── never a platform event ─────────────────────────────────────────────────────────


def test_platform_events_never_reach_a_workspace(db_session, world):
    from marvin.services.event_bus_service.event_types import Event, EventBusMessage
    from marvin.services.events.event_catalog import PLATFORM_EVENT_TYPES

    for name in PLATFORM_EVENT_TYPES:
        event_type = EventTypes[name]
        event = Event(
            message=EventBusMessage.from_type(event_type), event_type=event_type, integration_id=SOURCE, document_data=None, workspace_id=world.gid
        )
        assert not notes.wants(world.gid, event), name
    failed = Event(
        message=EventBusMessage.from_type(EventTypes.automation_failed),
        event_type=EventTypes.automation_failed,
        integration_id=SOURCE,
        document_data=None,
    )
    assert not notes.wants(None, failed)  # no workspace
    assert not notes.wants(world.gid, failed.model_copy(update={"workspace_id": world.other}))  # another workspace's

    # A platform event dispatched under this workspace's id reaches neither its email nor its incidents.
    EventBusService(bg_tasks=None).dispatch(
        integration_id=SOURCE,
        group_id=world.gid,
        event_type=EventTypes.backup_failed,
        document_data=EventBackupData(operation=EventOperation.info, target_name="r2", target_type="s3", status="failed", reason="failed"),
        message="Backup r2: failed",
    )
    _workflow(world, ok=False, group_id=world.other)  # another workspace's failure
    assert [to for to, *_ in world.sent if to in world.emails.values()] == []


# ── routes ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def providers(monkeypatch):
    pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")
    from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction

    class Chat(IntegrationProvider):
        """A Slack-like plugin: notify category, a message action that also needs a channel."""

        slug, name, category = "test_note_chat", "Test Chat", "notify"
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
        )
        calls: list = []

        def run_action(self, key, args, ctx):
            type(self).calls.append(dict(args))
            return {"ok": True}

    class Pager(IntegrationProvider):
        """An Apprise-like action: the notify capability, title + body."""

        slug, name, category = "test_note_pager", "Test Pager", "destination"
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
            type(self).calls.append(dict(args))
            return {}

    class Deploy(IntegrationProvider):
        slug, name, category = "test_note_deploy", "Test Deploy", "destination"
        actions = (ProviderAction(key="deploy", label="Deploy", input_schema={"type": "object", "properties": {"text": {"type": "string"}}}),)

        def run_action(self, key, args, ctx):
            raise AssertionError("a deploy hook must never carry a notification")

    for cls in (Chat, Pager, Deploy):
        monkeypatch.setitem(INTEGRATION_REGISTRY, cls.slug, cls())
    Chat.calls, Pager.calls = [], []
    return SimpleNamespace(chat=Chat, pager=Pager)


def _route(integration, action, kinds=None, **args):
    return {"integration_id": str(integration.id), "action": action, "args": args, "enabled": True, "kinds": kinds}


def test_each_route_takes_its_kinds(db_session, world, providers):
    chat = _connection(db_session, world, "test_note_chat", "Ops")
    pager = _connection(db_session, world, "test_note_pager", "Oncall")
    _configure(
        db_session,
        world,
        email=False,
        routes=[_route(chat, "post", kinds=["scheduled_task_failed"], channel="#ops"), _route(pager, "page")],
    )
    _workflow(world, ok=False)
    assert providers.chat.calls == []  # this route takes scheduled task failures only
    (page,) = providers.pager.calls
    assert page["title"] == "Workflow failed: Nightly sync" and "/automation/workflows?workflow=" in page["body"]

    EventBusService(bg_tasks=None).dispatch(
        integration_id=SOURCE,
        group_id=world.gid,
        event_type=EventTypes.scheduled_task_failed,
        document_data=EventScheduledTaskData(
            operation=EventOperation.info, task_id=uuid.uuid4(), task_name="Poll", task_slug="poll", task_type="x", workspace_id=world.gid
        ),
        message="Scheduled task 'Poll' failed: boom",
    )
    (post,) = providers.chat.calls
    assert post["channel"] == "#ops" and post["text"].startswith("*Scheduled task failed: Poll*\nScheduled task 'Poll' failed: boom")
    assert len(providers.pager.calls) == 2


@pytest.mark.parametrize(
    ("route", "detail"),
    [
        ({"action": "post", "args": {"channel": "#x"}, "kinds": ["nope"]}, "Unknown alert type"),
        ({"action": "post", "args": {"channel": "#x"}, "kinds": []}, "takes no kind"),
        ({"action": "post", "args": {}}, "needs channel"),
        ({"action": "deploy", "args": {}}, "can't carry alerts from this workspace"),
    ],
)
def test_routes_that_cannot_work_are_refused(db_session, world, providers, route, detail):
    chat = _connection(db_session, world, "test_note_chat", "Ops")
    deploy = _connection(db_session, world, "test_note_deploy", "Site")
    target = deploy if route["action"] == "deploy" else chat
    with pytest.raises(alerting.InvalidAlertSettings, match=detail):
        _configure(db_session, world, routes=[{**route, "integration_id": str(target.id)}])


def test_another_workspaces_connection_cannot_be_a_route(db_session, world, providers):
    from marvin.db.models.groups.integrations import IntegrationModel

    foreign = IntegrationModel(
        session=db_session, group_id=world.other, provider="test_note_chat", name="Theirs", slug=f"theirs-{world.marker}", config={}
    )
    db_session.add(foreign)
    db_session.commit()
    with pytest.raises(alerting.InvalidAlertSettings, match="can't carry alerts from this workspace"):
        _configure(db_session, world, routes=[_route(foreign, "post", channel="#x")])


# ── API ───────────────────────────────────────────────────────────────────────────


def _sign_in(world, role: str | None, platform_role=PlatformRole.NONE) -> TestClient:
    workspace_role = WorkspaceRole[role.upper()] if role else None
    uid = world.users.get(role or "viewer")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uid,
        group_id=world.gid,
        active_group_id=world.gid,
        admin=False,
        is_superuser=False,
        full_name=f"{(role or 'no').title()} Person",
        username=f"{role}-{world.marker}",
        email=f"{role}-{world.marker}@example.test",
        platform_role=platform_role,
        workspace_memberships=[SimpleNamespace(group_id=world.gid, workspace_role=workspace_role)] if workspace_role else [],
        get_workspace_role=lambda group_id: workspace_role if str(group_id) == str(world.gid) else None,
    )
    return TestClient(app)


@pytest.mark.parametrize("role", ["editor", "author", "viewer", None])
def test_only_owners_and_admins_may_read_change_or_test(world, role):
    client = _sign_in(world, role)
    assert client.get(API).status_code == 403
    assert client.put(API, json={"types": {"ai_operation_failed": True}}).status_code == 403
    assert client.post(f"{API}/test", json={"channel": "email"}).status_code == 403
    assert world.sent == []


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owners_and_admins_read_the_settings(world, role):
    res = _sign_in(world, role).get(API)
    assert res.status_code == 200, res.text
    body = res.json()
    assert {t["key"]: t["enabled"] for t in body["types"]}["ai_operation_failed"] is False
    assert body["email"]["enabled"] is True and body["email"]["recipients"] is None and body["email"]["kinds"] is None
    assert set(body["email"]["adminEmails"]) == {world.emails["owner"], world.emails["admin"]}
    assert body["integrationReminderHours"] == 24 and body["routes"] == []


def test_saving_validates_persists_and_audits(db_session, world):
    from marvin.db.models.platform.event_log import EventLogModel

    client = _sign_in(world, "admin")
    res = client.put(
        API,
        json={
            "types": {"ai_operation_failed": True, "scheduled_task_failed": False},
            "email": {"enabled": True, "recipients": ["ops@example.test", "OPS@example.test"], "kinds": ["workflow_failed"]},
            "integrationReminderHours": 6,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email"]["recipients"] == ["ops@example.test"] and body["email"]["kinds"] == ["workflow_failed"]
    assert body["integrationReminderHours"] == 6
    assert client.get(API).json()["email"]["recipients"] == ["ops@example.test"]  # persisted

    db_session.expire_all()
    (row,) = db_session.query(EventLogModel).filter(EventLogModel.workspace_id == world.gid, EventLogModel.integration_id == "notifications").all()
    assert row.event_type == "workspace_settings_changed"
    message = row.message_body
    assert "AI operation failed: on" in message and "Email recipients: 1 address(es)" in message and "reminders: every 6 h" in message
    rebuilds = db_session.query(EventLogModel).filter(EventLogModel.workspace_id == world.gid, EventLogModel.event_type == "site_rebuild_queued")
    assert rebuilds.count() == 0  # no site shows these settings

    for payload, detail in (
        ({"types": {"backup_failed": True}}, "Unknown alert type"),  # a platform kind isn't a workspace's
        ({"email": {"recipients": ["not-an-email"]}}, "isn't an email address"),
        ({"email": {"recipients": []}}, "every owner and admin"),
    ):
        res = client.put(API, json=payload)
        assert res.status_code == 422 and detail in res.text, res.text


def test_the_test_button_sends_through_one_channel(db_session, world):
    _configure(db_session, world, email=False, recipients=["ops@example.test"])
    client = _sign_in(world, "owner")
    res = client.post(f"{API}/test", json={"channel": "email"})  # off, but a test still goes
    assert res.status_code == 200, res.text
    assert res.json()["delivery"]["outcome"] == "sent" and res.json()["delivery"]["test"] is True
    assert [(to, subject) for to, subject, _ in world.sent] == [("ops@example.test", notes.TEST_TITLE)]
    assert client.get(API).json()["email"]["lastDelivery"]["test"] is True
    assert client.post(f"{API}/test", json={"channel": "no-such-route"}).status_code == 404


def test_the_test_button_on_a_route(db_session, world, providers):
    chat = _connection(db_session, world, "test_note_chat", "Ops")
    settings = _configure(db_session, world, routes=[_route(chat, "post", channel="#ops")])
    res = _sign_in(world, "admin").post(f"{API}/test", json={"channel": settings.routes[0].id})
    assert res.status_code == 200 and res.json()["delivery"]["outcome"] == "sent", res.text
    (call,) = providers.chat.calls
    assert call["channel"] == "#ops" and call["text"].startswith(f"*{notes.TEST_TITLE}*")


# ── the Integration alerts panel's routing, migrated ────────────────────────────────

_MIGRATION = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_cfbbd1cc67e4_*.py"))
_spec = importlib.util.spec_from_file_location("workspace_notifications_migration", _MIGRATION)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture
def scratch():
    """An in-memory DB with just the tables and columns the data migration reads and writes."""
    import marvin.db.migration_types as mt

    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    guid = mt.GUID
    sa.Table("integrations", meta, sa.Column("id", guid(), primary_key=True), sa.Column("group_id", guid()))
    sa.Table("email_templates", meta, sa.Column("id", guid(), primary_key=True), sa.Column("group_id", guid()), sa.Column("template_type", sa.String))
    sa.Table(
        "email_event_subscriptions",
        meta,
        *(sa.Column(c, guid()) for c in ("id", "group_id", "template_id")),
        sa.Column("event_type", sa.String),
        sa.Column("recipient_type", sa.String),
        sa.Column("enabled", sa.Boolean),
    )
    sa.Table(
        "integration_event_subscriptions",
        meta,
        *(sa.Column(c, guid()) for c in ("id", "group_id", "integration_id")),
        sa.Column("event_type", sa.String),
        sa.Column("action", sa.String),
        sa.Column("args", sa.JSON),
        sa.Column("enabled", sa.Boolean),
    )
    sa.Table(
        "group_preferences", meta, sa.Column("id", guid(), primary_key=True), sa.Column("group_id", guid()), sa.Column("notifications_json", sa.JSON)
    )
    sa.Table(
        "integration_alerts",
        meta,
        sa.Column("id", guid(), primary_key=True),
        sa.Column("group_id", guid()),
        sa.Column("status", sa.String),
        sa.Column("channels", sa.JSON),
    )
    meta.create_all(engine)
    with engine.begin() as conn:
        yield conn, meta.tables


def test_the_panels_routing_moves_to_the_notification_settings(scratch):
    conn, t = scratch
    template, panel_ws, quiet_ws, bare_ws = (uuid.uuid4() for _ in range(4))
    slack, apprise, hook = (uuid.uuid4() for _ in range(3))
    email_row, slack_row, apprise_row, custom_row, custom_email = (uuid.uuid4() for _ in range(5))
    open_alert, resolved_alert = uuid.uuid4(), uuid.uuid4()
    conn.execute(t["email_templates"].insert(), [{"id": template, "group_id": None, "template_type": "integration_alert"}])
    conn.execute(
        t["integrations"].insert(), [{"id": slack, "group_id": panel_ws}, {"id": apprise, "group_id": panel_ws}, {"id": hook, "group_id": quiet_ws}]
    )
    conn.execute(t["group_preferences"].insert(), [{"id": uuid.uuid4(), "group_id": g} for g in (panel_ws, quiet_ws, bare_ws)])
    needed = "integration_attention_needed"
    conn.execute(
        t["email_event_subscriptions"].insert(),
        [
            {"id": email_row, "group_id": panel_ws, "template_id": template, "event_type": needed, "recipient_type": "admins", "enabled": True},
            {"id": custom_email, "group_id": panel_ws, "template_id": template, "event_type": needed, "recipient_type": "specific", "enabled": False},
        ],
    )
    conn.execute(
        t["integration_event_subscriptions"].insert(),
        [
            {
                "id": slack_row,
                "group_id": panel_ws,
                "integration_id": slack,
                "event_type": needed,
                "action": "send_message",
                "args": {"text": "*{{title}}*\n{{summary}}"},
                "enabled": True,
            },
            {
                "id": apprise_row,
                "group_id": panel_ws,
                "integration_id": apprise,
                "event_type": needed,
                "action": "notify",
                "args": {"title": "{{title}}", "body": "{{summary}}"},
                "enabled": False,
            },
            # set up on the Events page: not the panel's, left alone
            {
                "id": custom_row,
                "group_id": panel_ws,
                "integration_id": slack,
                "event_type": needed,
                "action": "send_message",
                "args": {"text": "{{summary}}", "channel": "#x"},
                "enabled": True,
            },
        ],
    )
    conn.execute(
        t["integration_alerts"].insert(),
        [
            {
                "id": open_alert,
                "group_id": panel_ws,
                "status": "open",
                "channels": {"email": [str(email_row)], "integration": [str(slack_row), str(custom_row)]},
            },
            {"id": resolved_alert, "group_id": panel_ws, "status": "resolved", "channels": {"email": [str(email_row)], "integration": []}},
        ],
    )

    mig.migrate_panel_routing(conn)

    stored = dict(conn.execute(sa.select(t["group_preferences"].c.group_id, t["group_preferences"].c.notifications_json)).all())
    panel = stored[panel_ws]
    assert panel["email"] == {"enabled": True, "recipients": None}  # its email row was on: email takes every kind
    by_integration = {r["integration_id"]: r for r in panel["routes"]}
    assert set(by_integration) == {str(slack), str(apprise)}
    assert by_integration[str(slack)]["enabled"] is True and by_integration[str(apprise)]["enabled"] is False
    assert all(r["kinds"] == ["integration_attention"] and r["args"] == {} for r in panel["routes"])
    # a workspace with a connection but no panel email: its email keeps not getting integration alerts
    assert stored[quiet_ws]["email"]["kinds"] == mig.OTHER_KINDS and stored[quiet_ws]["routes"] == []
    assert stored[bare_ws] is None  # nothing that could alert: the defaults

    channels = dict(conn.execute(sa.select(t["integration_alerts"].c.id, t["integration_alerts"].c.channels)).all())
    assert channels[open_alert] == {"email": [], "integration": [str(custom_row)], "notify": sorted(["email", by_integration[str(slack)]["id"]])}
    assert channels[resolved_alert] == {"email": [str(email_row)], "integration": []}  # history untouched

    left = {r for (r,) in conn.execute(sa.select(t["email_event_subscriptions"].c.id))} | {
        r for (r,) in conn.execute(sa.select(t["integration_event_subscriptions"].c.id))
    }
    assert left == {custom_email, custom_row}


def test_migrated_settings_deliver_integration_alerts_as_the_panel_did(db_session, world):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    def store(value):
        db_session.query(GroupPreferencesModel).filter_by(group_id=world.gid).update({"notifications_json": value})
        db_session.commit()

    store(mig.settings_for(False, []))
    assert notes.channels_for(db_session, world.gid, "integration_attention") == []  # no panel email: none now
    assert notes.channels_for(db_session, world.gid, "workflow_failed") == ["email"]
    route = {"id": "r1", "integration_id": str(uuid.uuid4()), "action": "notify", "args": {}, "enabled": True, "kinds": ["integration_attention"]}
    store(mig.settings_for(True, [route]))
    assert notes.channels_for(db_session, world.gid, "integration_attention") == ["email", "r1"]
    assert notes.channels_for(db_session, world.gid, "workflow_failed") == ["email"]  # the route takes only what the panel sent it


# ── backups ─────────────────────────────────────────────────────────────────────────


def test_the_settings_travel_with_a_workspace_backup(db_session, world):
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.repos.all_repositories import get_repositories
    from marvin.repos.seed.workspace_exporter import WorkspaceExporter
    from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

    source = _connection(db_session, world, "test_note_chat", "Ops")
    stored = {
        "types": {"ai_operation_failed": True},
        "email": {"enabled": True, "recipients": ["ops@example.test"]},
        "routes": [
            {
                "id": "r1",
                "integration_id": str(source.id),
                "action": "post",
                "args": {"channel": "#ops"},
                "enabled": True,
                "kinds": ["workflow_failed"],
            }
        ],
    }
    db_session.query(GroupPreferencesModel).filter_by(group_id=world.gid).update({"notifications_json": stored})
    db_session.commit()

    data = WorkspaceExporter(get_repositories(db_session, group_id=world.gid)).export_workspace()
    assert data["notifications"]["routes"][0]["integrationSlug"] == source.slug
    res = WorkspaceSeedLoader(get_repositories(db_session, group_id=None))._load_data(data, overwrite=True, target_group_id=str(world.other))
    assert res["notifications"] == 1

    from marvin.db.models.groups.integrations import IntegrationModel

    copy = db_session.query(IntegrationModel).filter_by(group_id=world.other, slug=source.slug).one()
    restored = notes.load(db_session, world.other)
    assert restored.types["ai_operation_failed"] is True and restored.recipients == ["ops@example.test"]
    (route,) = restored.routes
    assert (route.integration_id, route.args, route.kinds) == (str(copy.id), {"channel": "#ops"}, ["workflow_failed"])
