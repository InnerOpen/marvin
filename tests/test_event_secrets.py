"""No live credential travels on the event bus, and workspace subscriptions never see platform events.

The audit that prompted this found three leaks:

* `user_password_reset_requested` carried the live reset URL and was dispatched under the user's workspace, where
  every listener ran: a workspace ADMIN could subscribe a webhook, an email (to any address) or an integration to it,
  ask /forgot-password for any user whose primary workspace that was (an OWNER, a super admin) and receive the link.
  The URL was also stored in the Event Log and in webhook execution logs.
* `invitation_*` events stored the live invitation token and URL, and any member (VIEWER included) reads full
  `event_data` from `GET /api/platform/events/{event_id}`.
* `GroupRead.webhooks` (URL, headers, custom payload) went to every member from `/api/self/workspaces`.

Now the reset and invitation emails are sent directly by the code that mints the link (the reset email always from
the platform's own template and sender); the events say who and when, nothing more; the webhook, integration, workflow
and email listeners skip platform events (existing subscriptions included) and the subscription routes refuse them;
GroupRead carries no webhooks.
"""

import logging
import re
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.core import security
from marvin.core.config import get_app_settings
from marvin.core.dependencies import get_current_user
from marvin.core.root_logger import get_logger
from marvin.db.models.users.roles import WorkspaceRole
from marvin.repos.all_repositories import get_repositories
from marvin.services.event_bus_service.event_types import EventTypes
from tests import test_event_connections as evc

PASSWORD = "correct horse battery staple"
LINK = re.compile(r"https?://[^\s\"'<>]+[?&]token=([A-Za-z0-9_\-]+)")


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def world(db_session, monkeypatch):
    """Workspace A: an OWNER (the victim, with a real password), an ADMIN and a VIEWER. Email and outgoing HTTP are
    captured, never sent; every log line is recorded."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    tag = uuid.uuid4().hex[:8]
    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"evsec-{tag}", slug=f"evsec-{tag}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    ids = {}
    for name, role in (("owner", WorkspaceRole.OWNER), ("admin", WorkspaceRole.ADMIN), ("viewer", WorkspaceRole.VIEWER)):
        ids[name] = uuid.uuid4()
        db_session.execute(
            Users.__table__.insert().values(
                id=ids[name],
                group_id=gid,
                username=f"evsec-{tag}-{name}",
                email=f"evsec-{tag}-{name}@t.test",
                full_name=f"{name.title()} Person",
                password=security.hash_password(PASSWORD),
                is_superuser=False,
                platform_role="NONE",
                auth_method="MARVIN",
            )
        )
        db_session.execute(WorkspaceMembers.__table__.insert().values(id=uuid.uuid4(), user_id=ids[name], group_id=gid, workspace_role=role))
    db_session.commit()

    sent: list[SimpleNamespace] = []  # every email, with the sender class that would have sent it
    from marvin.services.email import email_senders
    from marvin.services.email.email_service import EmailService

    for cls in (email_senders.DefaultEmailSender, email_senders.WorkspaceEmailSender):
        monkeypatch.setattr(
            cls,
            "send",
            lambda self, to, subject, html: sent.append(SimpleNamespace(to=to, subject=subject, html=html, by=type(self).__name__)) or True,
        )
    monkeypatch.setattr(EmailService, "_can_send", lambda self: True)
    monkeypatch.setattr(type(get_app_settings()), "SMTP_ENABLED", property(lambda self: True))

    posted: list = []  # every outgoing webhook request
    from marvin.services.event_bus_service import publisher

    def fake(method):
        def call(url, json=None, headers=None, timeout=None):
            posted.append(SimpleNamespace(method=method, url=url, json=json))
            return SimpleNamespace(status_code=200, ok=True, text="", raise_for_status=lambda: None)

        return call

    for method in ("get", "post", "put", "delete"):
        monkeypatch.setattr(publisher.requests, method, fake(method))

    logs = _Records()
    get_logger().addHandler(logs)

    def client(name: str) -> TestClient:
        user = get_repositories(db_session, group_id=None).users.get_one(ids[name], "id", any_case=False)
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield SimpleNamespace(
        a=gid, tag=tag, ids=ids, email={n: f"evsec-{tag}-{n}@t.test" for n in ids}, sent=sent, posted=posted, logs=logs, client=client
    )

    get_logger().removeHandler(logs)
    app.dependency_overrides.pop(get_current_user, None)
    from marvin.db.models.groups.invite_tokens import GroupInviteToken
    from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
    from marvin.db.models.users.password_reset import PasswordResetModel

    db_session.rollback()
    db_session.execute(sa.delete(WebhookExecutionLogModel).where(WebhookExecutionLogModel.group_id == gid))
    db_session.execute(sa.delete(PasswordResetModel).where(PasswordResetModel.user_id.in_(list(ids.values()))))
    db_session.execute(sa.delete(GroupInviteToken).where(GroupInviteToken.group_id == gid))
    db_session.execute(sa.delete(WorkspaceMembers).where(WorkspaceMembers.group_id == gid))
    db_session.commit()
    evc._purge(db_session, gid)


def _event_rows(db, gid, event_type: str) -> list:
    from marvin.db.models.platform.event_log import EventLogModel

    db.expire_all()
    return db.query(EventLogModel).filter(EventLogModel.workspace_id == gid, EventLogModel.event_type == event_type).all()


# ── 1. password reset ────────────────────────────────────────────────────────


def test_a_workspace_admins_subscriptions_never_receive_a_reset_link(db_session, world):
    """The attack: subscriptions to the reset event (made before the routes refused them, so made here directly) on
    every channel a workspace admin controls, then /forgot-password for the workspace's OWNER."""
    from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
    from marvin.services.event_bus_service.event_bus_listener import IntegrationEventListener

    event = "user_password_reset_requested"
    hook = evc.webhook(db_session, world.a, "Grab", [event])
    evc.esub(db_session, world.a, evc.template(db_session, world.a, "Grab"), event, recipient_type="specific")  # to secret-person@t.test
    evc.isub(db_session, world.a, evc.integration(db_session, world.a), event)

    res = TestClient(app).post("/api/users/forgot-password", json={"email": world.email["owner"]})
    assert res.status_code == 202, res.text

    # The reset email goes to the user, once, from the platform's own sender.
    assert [(m.to, m.by) for m in world.sent] == [(world.email["owner"], "DefaultEmailSender")]
    (token,) = set(LINK.findall(world.sent[0].html))

    # Nothing reaches the admin's subscriptions, and nothing stores or logs the token.
    assert world.posted == []
    assert IntegrationEventListener(world.a).get_subscribers(SimpleNamespace(event_type=EventTypes[event], document_data=None)) == []
    (row,) = _event_rows(db_session, world.a, event)
    assert token not in str(row.event_data) and "resetUrl" not in str(row.event_data)
    assert row.event_data["documentData"]["email"] == world.email["owner"]  # still says who
    assert db_session.query(WebhookExecutionLogModel).filter(WebhookExecutionLogModel.webhook_id == hook.id).count() == 0
    assert not [line for line in world.logs.lines if token in line]

    # And the link works.
    res = TestClient(app).post(
        "/api/users/reset-password",
        json={"token": token, "email": world.email["owner"], "password": "a brand new password", "passwordConfirm": "a brand new password"},
    )
    assert res.status_code == 200, res.text
    owner = get_repositories(db_session, group_id=None).users.get_one(world.ids["owner"], "id", any_case=False)
    assert security.verify_password("a brand new password", owner.password)


def test_a_workspace_password_reset_template_is_not_used(db_session, world):
    """A workspace template would put the link inside content the workspace admin wrote (an <img src=…{{reset_url}}>
    leaks it with no click), so the reset email is the platform's own: the API refuses a workspace copy, and one made
    before that is never used."""
    res = world.client("admin").post(
        f"/api/platform/workspaces/{world.a}/email-templates",
        json={"name": "Ours", "subject": "Reset", "templateType": "password_reset", "bodyMarkdown": "{{reset_url}}"},
    )
    assert res.status_code == 422, res.text

    evc.template(db_session, world.a, "Ours", template_type="password_reset")
    assert TestClient(app).post("/api/users/forgot-password", json={"email": world.email["owner"]}).status_code == 202
    (mail,) = world.sent
    assert mail.subject != "Hi" and LINK.search(mail.html)  # evc.template's subject is "Hi"


@pytest.mark.parametrize(
    "event",
    ["user_password_reset_requested", "user_signup", "api_token_created", "workspace_updated"],
)
def test_no_workspace_listener_reacts_to_a_platform_event(db_session, world, event):
    from marvin.services.event_bus_service.event_bus_listener import (
        AutomationReactionListener,
        EmailEventListener,
        IntegrationEventListener,
        WebhookEventListener,
    )

    evc.webhook(db_session, world.a, "W", [event])
    evc.isub(db_session, world.a, evc.integration(db_session, world.a), event)
    evc.esub(db_session, world.a, evc.template(db_session, world.a, "Note"), event, recipient_type="specific")
    happened = SimpleNamespace(event_type=EventTypes[event], document_data=None, reaction_depth=0)
    for listener in (WebhookEventListener, IntegrationEventListener, AutomationReactionListener):
        assert listener(world.a).get_subscribers(happened) == []
    # Email: no workspace subscription; at most Marvin's own system email (welcome), to the event's own address.
    for sub in EmailEventListener(world.a).get_subscribers(happened):
        assert getattr(sub, "recipient_type", None) == "event_field"
    # The event page agrees: nothing of the workspace's runs.
    from marvin.services.events import connections

    assert not [
        r
        for r in connections.reactions(db_session, world.a, event)
        if r.enabled and r.kind in ("webhook", "integration_action", "email") and r.detail != "System template"
    ]


def test_subscribing_to_a_platform_event_is_refused(db_session, world):
    event = "user_password_reset_requested"
    admin = world.client("admin")
    tmpl = evc.template(db_session, world.a, "Note")
    integ = evc.integration(db_session, world.a)

    res = admin.post(
        "/api/groups/webhooks", json={"name": "W", "url": "https://hooks.example.test/x", "webhookType": "event_driven", "subscribedEvents": [event]}
    )
    assert res.status_code == 422, res.text
    res = admin.post(
        "/api/groups/email-event-subscriptions",
        json={"templateId": str(tmpl.id), "eventType": event, "recipientType": "specific", "recipientEmail": "x@evil.test"},
    )
    assert res.status_code == 422, res.text
    res = admin.post("/api/groups/integrations/subscriptions", json={"integrationId": str(integ.id), "eventType": event, "action": "notify"})
    assert res.status_code == 422, res.text

    # Not vacuous: a workspace event is accepted.
    res = admin.post(
        "/api/groups/email-event-subscriptions", json={"templateId": str(tmpl.id), "eventType": "entry_published", "recipientType": "admins"}
    )
    assert res.status_code == 201, res.text


def test_a_webhook_cannot_be_updated_onto_a_platform_event(db_session, world):
    admin = world.client("admin")
    body = {"name": "W", "url": "https://hooks.example.test/x", "webhookType": "event_driven", "subscribedEvents": ["entry_published"]}
    res = admin.post("/api/groups/webhooks", json=body)
    assert res.status_code == 201, res.text
    res = admin.put(f"/api/groups/webhooks/{res.json()['id']}", json={**body, "subscribedEvents": ["entry_published", "user_signup"]})
    assert res.status_code == 422, res.text


# ── 2. invitations ───────────────────────────────────────────────────────────


def test_a_viewer_reads_no_invitation_token_from_the_event_log(db_session, world):
    admin = world.client("admin")
    res = admin.post("/api/groups/invitations", json={"usesLeft": 5, "workspaceRole": "VIEWER"})
    assert res.status_code in (200, 201), res.text
    token, invitation_id = res.json()["token"], res.json()["id"]
    invitee = f"evsec-{world.tag}-invitee@t.test"
    res = admin.post("/api/groups/invitations/email", json={"email": invitee, "token": token})
    assert res.status_code == 200 and res.json()["success"] is True, res.text

    # The invitee gets the email with a link that carries the live token.
    (mail,) = [m for m in world.sent if m.to == invitee]
    (link,) = {m.group(0) for m in LINK.finditer(mail.html)}
    assert parse_qs(urlparse(link).query)["token"] == [token] and urlparse(link).path.rstrip("/").endswith("/register")

    viewer = world.client("viewer")
    rows = _event_rows(db_session, world.a, "invitation_created") + _event_rows(db_session, world.a, "invitation_sent")
    assert {r.event_type for r in rows} == {"invitation_created", "invitation_sent"}
    for row in rows:
        res = viewer.get(f"/api/platform/events/{row.event_id}")
        assert res.status_code == 200, res.text
        assert token not in res.text
        assert res.json()["eventData"]["documentData"]["invitationId"] == invitation_id  # still says which invitation

    # Revoking: the event names the invitation by id, not by token.
    admin = world.client("admin")  # (the client follows the last override)
    assert admin.delete(f"/api/groups/invitations/{invitation_id}").status_code == 204  # by id, as the members page does
    (revoked,) = _event_rows(db_session, world.a, "invitation_revoked")
    assert token not in str(revoked.event_data)
    assert not [line for line in world.logs.lines if token in line]


def test_an_invitation_is_revoked_by_its_id_never_by_its_token(db_session, world):
    """The token is the invite's secret; a path carrying it lands in request logs, so the API doesn't take it."""
    admin = world.client("admin")
    res = admin.post("/api/groups/invitations", json={"usesLeft": 1, "workspaceRole": "VIEWER"})
    token, invitation_id = res.json()["token"], res.json()["id"]

    assert admin.delete(f"/api/groups/invitations/{token}").status_code == 404
    assert _event_rows(db_session, world.a, "invitation_revoked") == []
    assert admin.delete(f"/api/groups/invitations/{invitation_id}").status_code == 204


def test_a_workspace_invitation_template_still_replaces_marvins(db_session, world):
    """The invitation is the workspace's own (its admins mint the token), so its connected template still replaces
    Marvin's — sent to the invitee, whatever the connection's recipients say."""
    admin = world.client("admin")
    res = admin.post(
        f"/api/platform/workspaces/{world.a}/email-templates",
        json={"name": "Ours", "subject": "Join {{workspace_name}}", "templateType": "invitation", "bodyMarkdown": "Come in: {{invitation_url}}"},
    )
    assert res.status_code == 201, res.text
    token = admin.post("/api/groups/invitations", json={"usesLeft": 1, "workspaceRole": "VIEWER"}).json()["token"]
    invitee = f"evsec-{world.tag}-invitee@t.test"
    assert admin.post("/api/groups/invitations/email", json={"email": invitee, "token": token}).json()["success"] is True
    (mail,) = world.sent
    assert mail.to == invitee and mail.subject == f"Join evsec-{world.tag}" and f"token={token}" in mail.html


# ── 3. GroupRead.webhooks ────────────────────────────────────────────────────


def test_a_members_workspace_responses_carry_no_webhooks(db_session, world):
    evc.webhook(db_session, world.a, "Secret hook", ["entry_published"])
    viewer = world.client("viewer")
    for path in ("/api/self/workspaces", "/api/self/workspaces/current"):
        res = viewer.get(path)
        assert res.status_code == 200, res.text
        assert "webhooks" not in res.text and "hooks.example" not in res.text
    assert "webhooks" not in app.openapi()["components"]["schemas"]["GroupRead"]["properties"]


# ── smaller fixes ────────────────────────────────────────────────────────────


def test_the_admin_reset_token_endpoint_returns_the_token(db_session, world, monkeypatch):
    from marvin.db.models.users.roles import PlatformRole

    admin = get_repositories(db_session, group_id=None).users.get_one(world.ids["admin"], "id", any_case=False)
    admin.platform_role = PlatformRole.SUPER_ADMIN
    app.dependency_overrides[get_current_user] = lambda: admin
    res = TestClient(app).post("/api/admin/users/password-reset-token", json={"email": world.email["owner"]})
    assert res.status_code == 201, res.text
    assert res.json()["email"] == world.email["owner"] and res.json()["token"]


def test_the_console_listener_logs_no_credential(world):
    from marvin.services.event_bus_service.event_types import Event, EventBusMessage, EventIncomingWebhookData, EventOperation
    from marvin.services.event_bus_service.publisher import ConsolePublisher

    event = Event(
        message=EventBusMessage.from_type(EventTypes.incoming_webhook, body="x"),
        event_type=EventTypes.incoming_webhook,
        integration_id="t",
        document_data=EventIncomingWebhookData(
            operation=EventOperation.info,
            webhook_id=uuid.uuid4(),
            webhook_slug="s",
            webhook_name="n",
            payload={"apiToken": "tok-SHOULD-NOT-APPEAR", "nested": {"password": "pw-SHOULD-NOT-APPEAR"}, "plain": "visible"},
            workspace_id=world.a,
        ),
        workspace_id=world.a,
    )
    ConsolePublisher().publish(event, ["console"])
    text = "\n".join(world.logs.lines)
    assert "visible" in text and "SHOULD-NOT-APPEAR" not in text
