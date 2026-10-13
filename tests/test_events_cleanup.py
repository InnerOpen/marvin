"""Events hub, slice 5: the catalog cleanup.

* Hidden types (nothing sends them, or an old name) are offered and listed nowhere: the workspace event types, the
  admin Events filter, the connections summary and detail.
* `webhook_triggered` reads as "Site Rebuild Sent" under Publishing.
* Newly sent: webhook_created/updated/deleted from the outgoing-webhook routes, webhook_delivery_failed once per
  delivery that failed after its retries, api_token_created/rotated/revoked from the personal-token routes — none
  carrying a URL, headers, a body or a token.
* site_build_* are aliases of site_deployment_*: workflow triggers, Emit event steps and subscriptions that name one
  are stored, read and run as the counterpart; the migration's rewrite is idempotent.
"""

import importlib.util
import json
import pathlib
import uuid

import pytest
import requests
import sqlalchemy as sa

from marvin.db.models.users.roles import PlatformRole
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import Event, EventBusMessage, EventTypes
from marvin.services.events.event_catalog import CATALOG, HIDDEN_EVENT_TYPES
from tests import test_event_connections as evc

world = evc.world  # the shared two-workspace fixture
ADMIN, WS = evc.ADMIN, evc.WS
_client, esub, integration, isub, template, webhook, workflow = (
    evc._client,
    evc.esub,
    evc.integration,
    evc.isub,
    evc.template,
    evc.webhook,
    evc.workflow,
)

SECRET_URL = "https://hooks.example.test/very-secret-token"


@pytest.fixture
def dispatched(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: seen.append(kw))
    return seen


def _payload(call: dict) -> str:
    return json.dumps(call["document_data"].model_dump(mode="json")) + call.get("message", "")


# ── hidden types are listed nowhere ──────────────────────────────────────────


def test_hidden_types_are_offered_nowhere_on_the_api(world):
    client = _client(world)
    offered = {e["value"]: e for e in client.get("/api/event/types").json()}
    assert offered and not HIDDEN_EVENT_TYPES & set(offered)
    assert (offered["webhook_triggered"]["label"], offered["webhook_triggered"]["category"]) == ("Site Rebuild Sent", "Publishing")
    assert {"webhook_created", "webhook_delivery_failed", "site_deployment_completed"} <= set(offered)

    summary = {r["eventType"] for r in client.get(f"{WS}/connections").json()}
    assert summary == {e.event_type for e in CATALOG if e.scope == "workspace" and not e.hidden}
    for name in ("site_build_completed", "webhook_delivery_succeeded", "site_published"):
        assert client.get(f"{WS}/{name}/connections").status_code == 404, name

    admin = _client(world, None, platform_role=PlatformRole.SUPER_ADMIN)
    platform = {r["eventType"] for r in admin.get("/api/admin/events/catalog").json()}
    assert "api_token_revoked" in platform and not HIDDEN_EVENT_TYPES & platform
    assert admin.get(f"{ADMIN}/suspicious_activity_detected/connections").status_code == 404
    assert admin.get(f"{ADMIN}/api_token_created/connections").status_code == 200


# ── outgoing webhooks announce their lifecycle ──────────────────────────────


def test_webhook_routes_send_created_updated_deleted_without_the_url_or_headers(world, dispatched):
    client = _client(world)
    body = {
        "name": "Deploy hook",
        "url": SECRET_URL,
        "webhookType": "event_driven",
        "headers": {"Authorization": "Bearer header-secret"},
        "subscribedEvents": ["webhook_triggered"],
    }
    res = client.post("/api/groups/webhooks", json=body)
    assert res.status_code == 201, res.text
    hook_id = res.json()["id"]
    assert client.put(f"/api/groups/webhooks/{hook_id}", json={**body, "enabled": False}).status_code == 200
    assert client.delete(f"/api/groups/webhooks/{hook_id}").status_code == 200

    calls = [c for c in dispatched if c["event_type"].name.startswith("webhook_")]
    assert [c["event_type"].name for c in calls] == ["webhook_created", "webhook_updated", "webhook_deleted"]
    for call in calls:
        data = call["document_data"]
        assert str(data.webhook_id) == hook_id and data.webhook_name == "Deploy hook" and data.webhook_type == "event_driven"
        assert data.subscribed_events == ["webhook_triggered"] and data.changed_by_name == "Events Person"
        assert call["user_id"] == world.ua and call["entity_type"] == "webhook" and call["group_id"] == world.a
        assert "very-secret-token" not in _payload(call) and "header-secret" not in _payload(call)
    assert [c["document_data"].enabled for c in calls] == [True, False, False]


# ── webhook_delivery_failed: once per failed delivery, after the retries ─────


@pytest.fixture
def quiet_delivery(monkeypatch):
    """No sleeping between retries, no execution-log rows."""
    import marvin.services.event_bus_service.publisher as publisher

    monkeypatch.setattr(publisher.time, "sleep", lambda _s: None)
    monkeypatch.setattr(publisher, "_log_webhook_execution", lambda **_kw: None)
    return publisher


def _event(name: str = "webhook_triggered") -> Event:
    et = EventTypes[name]
    return Event(message=EventBusMessage.from_type(et), event_type=et, integration_id="t", document_data=None, workspace_id=uuid.uuid4())


def _deliver(publisher, monkeypatch, outcome, event=None):
    attempts = []

    def post(url, **_kw):
        attempts.append(url)
        if isinstance(outcome, Exception):
            raise outcome
        response = requests.Response()
        response.status_code = outcome
        return response

    monkeypatch.setattr(publisher.requests, "post", post)
    hook_id, group_id = uuid.uuid4(), uuid.uuid4()
    publisher.WebhookPublisher().publish(
        event or _event(), [SECRET_URL], webhook_id=hook_id, group_id=group_id, headers={"X-Key": "header-secret"}, webhook_name="Deploy hook"
    )
    return attempts, hook_id, group_id


def test_a_delivery_that_fails_after_its_retries_is_announced_once(monkeypatch, quiet_delivery, dispatched):
    attempts, hook_id, group_id = _deliver(quiet_delivery, monkeypatch, 503)
    assert len(attempts) == quiet_delivery.MAX_RETRY_ATTEMPTS
    (call,) = dispatched
    data = call["document_data"]
    assert call["event_type"] == EventTypes.webhook_delivery_failed and call["group_id"] == group_id
    assert (data.webhook_id, data.webhook_name, data.delivered_event_type) == (hook_id, "Deploy hook", "webhook_triggered")
    assert (data.status_code, data.error_message, data.attempts) == (503, "HTTP 503", quiet_delivery.MAX_RETRY_ATTEMPTS)
    assert call["entity_id"] == hook_id and call["entity_type"] == "webhook"
    assert "very-secret-token" not in _payload(call) and "header-secret" not in _payload(call)


def test_a_connection_error_names_its_kind_never_the_url(monkeypatch, quiet_delivery, dispatched):
    _deliver(quiet_delivery, monkeypatch, requests.exceptions.ConnectionError(f"Max retries exceeded with url: {SECRET_URL}"))
    (call,) = dispatched
    assert call["document_data"].error_message == "ConnectionError" and call["document_data"].status_code is None
    assert "very-secret-token" not in _payload(call)


def test_a_delivery_that_recovers_or_succeeds_announces_nothing(monkeypatch, quiet_delivery, dispatched):
    _deliver(quiet_delivery, monkeypatch, 200)
    assert dispatched == []

    outcomes = iter([503, 200])

    def post(url, **_kw):
        response = requests.Response()
        response.status_code = next(outcomes)
        return response

    monkeypatch.setattr(quiet_delivery.requests, "post", post)
    quiet_delivery.WebhookPublisher().publish(_event(), [SECRET_URL], webhook_id=uuid.uuid4(), group_id=uuid.uuid4())
    assert dispatched == []


def test_a_failing_webhook_on_webhook_delivery_failed_does_not_loop(monkeypatch, quiet_delivery, dispatched):
    _deliver(quiet_delivery, monkeypatch, 500, event=_event("webhook_delivery_failed"))
    assert dispatched == []


def test_the_webhook_listener_names_the_webhook(db_session, world, monkeypatch):
    from marvin.services.event_bus_service.event_bus_listener import WebhookEventListener

    hook = webhook(db_session, world.a, "Deploy hook", ["webhook_triggered"])
    seen = []
    monkeypatch.setattr("marvin.services.event_bus_service.publisher.WebhookPublisher.publish", lambda self, event, urls, **kw: seen.append(kw))
    listener = WebhookEventListener(world.a)
    listener.publish_to_subscribers(_event(), listener.get_subscribers(_event()))
    assert [(kw["webhook_id"], kw["webhook_name"]) for kw in seen] == [(hook.id, "Deploy hook")]


# ── personal API tokens ──────────────────────────────────────────────────────


def test_personal_token_routes_send_created_rotated_revoked_without_the_token(db_session, world, dispatched):
    from marvin.db.models.users.users import LongLiveToken

    client = _client(world)
    try:
        res = client.post("/api/self/api-tokens", json={"name": "CI Deploy Token"})
        assert res.status_code == 201, res.text
        token_id, first_value = res.json()["id"], res.json()["token"]
        hashes = [db_session.get(LongLiveToken, uuid.UUID(token_id)).token_hash]
        rotated = client.post(f"/api/self/api-tokens/{token_id}/rotate")
        assert rotated.status_code == 200, rotated.text
        db_session.expire_all()
        hashes.append(db_session.get(LongLiveToken, uuid.UUID(token_id)).token_hash)
        assert client.post(f"/api/self/api-tokens/{token_id}/revoke").status_code == 200
        assert client.delete(f"/api/self/api-tokens/{token_id}").status_code == 200

        calls = [c for c in dispatched if c["event_type"].name.startswith("api_token_")]
        assert [c["event_type"].name for c in calls] == ["api_token_created", "api_token_rotated", "api_token_revoked", "api_token_revoked"]
        assert all(hashes)
        for call in calls:
            data = call["document_data"]
            assert str(data.token_id) == token_id and data.token_name == "CI Deploy Token"
            assert data.user_id == world.ua and data.user_name == "Events Person" and data.token_prefix is None
            assert call["user_id"] == world.ua and call["group_id"] == world.a and call["entity_type"] == "api_token"
            for secret in (first_value, rotated.json()["token"], *hashes):
                assert secret not in _payload(call)
        assert "deleted" in calls[-1]["message"] and "revoked" in calls[-2]["message"]
    finally:
        db_session.execute(sa.delete(LongLiveToken).where(LongLiveToken.user_id == world.ua))
        db_session.commit()


# ── site_build_* are old names for site_deployment_* ─────────────────────────


def test_a_workflow_naming_an_old_name_is_stored_and_read_as_the_counterpart(db_session, world):
    flow = workflow(
        db_session,
        world.a,
        "Old names",
        {"type": "event", "event": "site_build_failed"},
        actions=[{"kind": "emit_event", "event": "site_build_completed"}],
        on_failure=[{"kind": "emit_event", "event": "site_build_started"}],
    )
    assert flow.trigger_event == "site_deployment_failed"
    assert flow.body["actions"][0]["event"] == "site_deployment_completed"
    assert flow.body["on_failure"][0]["event"] == "site_deployment_started"
    assert flow.definition["trigger"] == {"type": "event", "event": "site_deployment_failed"}


def test_rows_stored_before_the_alias_read_and_run_as_the_counterpart(db_session, world):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation.engine import run_automations_for_event

    flow = workflow(
        db_session,
        world.a,
        "Legacy",
        {"type": "event", "event": "site_deployment_failed"},
        actions=[{"kind": "emit_event", "event": "entry_published"}],
    )
    table = WorkspaceAutomationModel.__table__
    db_session.execute(
        table.update()
        .where(table.c.id == flow.id)
        .values(trigger_event="site_build_failed", definition={"actions": [{"kind": "emit_event", "event": "site_build_completed"}]})
    )
    db_session.commit()
    db_session.expire_all()
    flow = db_session.get(WorkspaceAutomationModel, flow.id)
    assert flow.definition == {
        "trigger": {"type": "event", "event": "site_deployment_failed"},
        "actions": [{"kind": "emit_event", "event": "site_deployment_completed"}],
    }
    assert run_automations_for_event(db_session, world.a, {"event_type": "site_deployment_failed"}, dry_run=True) == 1


def test_the_workflow_api_accepts_old_names_and_returns_the_counterparts(world):
    client = _client(world)
    body = {
        "name": "Deploy failed",
        "enabled": False,
        "definition": {
            "trigger": {"type": "event", "event": "site_build_failed"},
            "actions": [{"kind": "emit_event", "event": "site_build_completed"}],
        },
    }
    res = client.post("/api/automations", json=body)
    assert res.status_code in (200, 201), res.text
    definition = res.json()["definition"]
    assert definition["trigger"]["event"] == "site_deployment_failed" and definition["actions"][0]["event"] == "site_deployment_completed"


def test_subscriptions_naming_an_old_name_are_stored_as_the_counterpart(db_session, world):
    hook = webhook(db_session, world.a, "Hook", ["site_build_completed", "site_deployment_completed", "site_build_failed"])
    assert hook.subscribed_events == ["site_deployment_completed", "site_deployment_failed"]
    note = esub(db_session, world.a, template(db_session, world.a, "Note"), "site_build_started")
    assert note.event_type == "site_deployment_started"
    action = isub(db_session, world.a, integration(db_session, world.a), "site_build_failed")
    assert action.event_type == "site_deployment_failed"


def _migration():
    versions = pathlib.Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions"
    (path,) = versions.glob("*_011f6c720d1d_*.py")
    spec = importlib.util.spec_from_file_location("site_build_alias_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_rewrites_old_names_idempotently(db_session, world):
    """Rows written the way the old code stored them (raw SQL) come out as the counterparts, and a second run
    changes nothing. A webhook already on the counterpart keeps one row."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
    from marvin.db.models.groups.webhook_event_subscriptions import WebhookEventSubscriptionModel

    flow = workflow(db_session, world.a, "Legacy", {"type": "event", "event": "entry_published"})
    both = webhook(db_session, world.a, "Both", ["site_deployment_completed", "entry_published"])
    one = webhook(db_session, world.a, "One", ["entry_published"])
    note = esub(db_session, world.a, template(db_session, world.a, "Note"), "entry_published")
    action = isub(db_session, world.a, integration(db_session, world.a), "entry_published")
    old_body = {"actions": [{"kind": "emit_event", "event": "site_build_failed"}, {"kind": "handler", "task": "request_site_rebuild"}]}
    wf, ws_ = WorkspaceAutomationModel.__table__, WebhookEventSubscriptionModel.__table__
    db_session.execute(wf.update().where(wf.c.id == flow.id).values(trigger_event="site_build_started", definition=old_body))
    db_session.execute(
        ws_.update().where(ws_.c.webhook_id.in_([both.id, one.id]), ws_.c.event_type == "entry_published").values(event_type="site_build_completed")
    )
    for model, row in ((EmailEventSubscriptionModel, note), (IntegrationEventSubscriptionModel, action)):
        db_session.execute(model.__table__.update().where(model.__table__.c.id == row.id).values(event_type="site_build_failed"))
    db_session.commit()

    migration = _migration()
    for _ in range(2):
        with Operations.context(MigrationContext.configure(db_session.connection())):
            migration.upgrade()
        db_session.commit()

    def raw(table, column, key, value):
        return [r[0] for r in db_session.execute(sa.select(table.c[column]).where(table.c[key] == value))]  # one row each

    assert raw(wf, "trigger_event", "id", flow.id) == ["site_deployment_started"]
    assert raw(wf, "definition", "id", flow.id)[0]["actions"] == [
        {"kind": "emit_event", "event": "site_deployment_failed"},
        {"kind": "handler", "task": "request_site_rebuild"},
    ]
    assert raw(ws_, "event_type", "webhook_id", both.id) == ["site_deployment_completed"]
    assert raw(ws_, "event_type", "webhook_id", one.id) == ["site_deployment_completed"]
    assert raw(EmailEventSubscriptionModel.__table__, "event_type", "id", note.id) == ["site_deployment_failed"]
    assert raw(IntegrationEventSubscriptionModel.__table__, "event_type", "id", action.id) == ["site_deployment_failed"]
