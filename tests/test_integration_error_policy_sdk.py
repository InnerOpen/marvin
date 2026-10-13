"""Integration-owned error handling against the real SDK (0.5.0+): the integration step resolves the
provider's declared error policy, hands a retry its partial progress and idempotency seed, honours a
connection's overrides, and the connection-scope callers alert without reviewing or retrying.

Skipped when the installed SDK predates error policies (core then behaves exactly as before — see
test_integration_error_handling.py for the engine side, which needs no SDK).
"""

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pytest import fixture

sdk = pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")
if not hasattr(sdk, "resolve_policy"):
    pytest.skip("integrations SDK predates error policies (< 0.5.0)", allow_module_level=True)

from marvin_integration_sdk import INTEGRATION_REGISTRY, Handle, IntegrationError, IntegrationProvider, ProviderAction, Retry  # noqa: E402

from marvin.services.automation.engine import run_automations_for_event, run_retry  # noqa: E402
from marvin.services.automation.recorder import ExecutionRecorder  # noqa: E402
from marvin.services.integrations import errors  # noqa: E402

WORKFLOW = {
    "trigger": {"type": "event", "event": "entry_published"},
    "conditions": [{"field": "entry.data.sell", "op": "eq", "value": True}],
    "actions": [{"kind": "integration", "id": "list", "integration": "shop", "action": "create_listing", "args": {"title": "${entry.title}"}}],
}


class _Shop(IntegrationProvider):
    slug = "policy_shop"
    name = "Policy Shop"
    error_policy = {
        "auth": Handle(notify=True, retry=Retry((), on_recovery=True)),
        "invalid": Handle(review=True),
    }
    actions = (
        ProviderAction(
            key="create_listing",
            label="Create listing",
            error_policy={"unavailable": Handle(retry=Retry((60,)), then=Handle(review=True))},
        ),
        ProviderAction(key="ping", label="Ping"),
    )

    def __init__(self):
        self.failures: list[Exception | None] = []
        self.contexts: list = []

    def run_action(self, key, args, ctx):
        self.contexts.append(ctx)
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            raise failure
        return {"listing_id": "L1"}


@fixture
def shop(db_session, monkeypatch):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform import Entries, EntryTypes

    provider = _Shop()
    monkeypatch.setitem(INTEGRATION_REGISTRY, provider.slug, provider)
    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService.dispatch", lambda self, *a, **k: None)
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"pol-{marker}", slug=f"pol-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    integration = IntegrationModel(session=db_session, group_id=gid, provider=provider.slug, name="Shop", slug="shop", enabled=True, config={})
    db_session.add(integration)
    db_session.add(WorkspaceAutomationModel(session=db_session, group_id=gid, name="List", slug="list", enabled=True, definition=WORKFLOW))
    et = EntryTypes(session=db_session, group_id=gid, name="Product", slug="product", schema_json={"fields": []})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    entry = Entries(
        session=db_session, group_id=gid, entry_type_id=et.id, title="Mug", slug=f"mug-{marker}", data_json={"sell": True}, status="draft"
    )
    db_session.add(entry)
    db_session.commit()
    yield SimpleNamespace(gid=gid, provider=provider, integration=integration, entry_id=entry.id)

    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel, IntegrationRetryModel
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    for model in (IntegrationRetryModel, IntegrationAlertModel, AutomationActionExecutionModel, AutomationExecutionModel):
        db_session.query(model).filter(model.group_id == gid).delete()
    db_session.query(WorkspaceAutomationModel).filter(WorkspaceAutomationModel.group_id == gid).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _publish(db_session, shop):
    event = {"event_type": "entry_published", "entry_id": str(shop.entry_id), "user_id": None}
    run_automations_for_event(db_session, shop.gid, event, recorder=ExecutionRecorder(db_session, shop.gid))
    db_session.expire_all()


def _retries(db_session, shop):
    from marvin.db.models.groups.integration_errors import IntegrationRetryModel

    return db_session.query(IntegrationRetryModel).filter_by(group_id=shop.gid).all()


def test_the_step_applies_the_providers_declared_policy_and_keeps_partial_progress(db_session, shop):
    from marvin.db.models.platform import Entries

    shop.provider.failures = [IntegrationError("price must be positive", code="invalid", partial={"item_id": "I1"}), None]

    _publish(db_session, shop)

    entry = db_session.get(Entries, shop.entry_id)
    assert entry.status == "needs_review"
    assert entry.metadata_json["integration_error"]["shop"]["message"] == "price must be positive"
    (row,) = _retries(db_session, shop)
    assert (row.status, row.partial) == ("failed", {"item_id": "I1"})  # no retry, but the progress is kept

    _publish(db_session, shop)

    second = shop.provider.contexts[1]
    assert second.resume == {"item_id": "I1"}  # the next run picks up where the last stopped
    assert second.idempotency_seed and second.idempotency_seed != shop.provider.contexts[0].idempotency_seed
    (row,) = _retries(db_session, shop)
    assert row.partial is None  # spent once the action succeeded


def test_a_retry_gets_the_chains_partial_and_the_same_idempotency_seed(db_session, shop):
    shop.provider.failures = [IntegrationError("try later", code="unavailable", partial={"order_id": "O1"}), None]

    _publish(db_session, shop)
    (row,) = _retries(db_session, shop)
    assert row.status == "pending" and row.handle["then"]["review"] is True  # the action's own policy wins
    row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    (claimed,) = errors.claim_due(db_session)

    assert run_retry(db_session, shop.gid, claimed, recorder=ExecutionRecorder(db_session, shop.gid)) == "succeeded"

    first, retry = shop.provider.contexts
    assert retry.resume == {"order_id": "O1"}
    assert retry.idempotency_seed == first.idempotency_seed  # same keys across the chain


def test_an_auth_failure_alerts_and_parks_until_a_passing_check(db_session, shop):
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel

    shop.provider.failures = [IntegrationError("token expired", code="auth")]

    _publish(db_session, shop)

    (row,) = _retries(db_session, shop)
    assert row.status == "parked"
    (alert,) = db_session.query(IntegrationAlertModel).filter_by(group_id=shop.gid).all()
    assert (alert.code, alert.status) == ("auth", "open")

    errors.connection_succeeded(shop.gid, shop.integration.id, resolution="check", session=db_session)
    db_session.expire_all()
    (row,) = _retries(db_session, shop)
    assert row.status == "pending"


def test_connection_overrides_adjust_review_and_notify_only():
    provider = _Shop()

    assert errors.policy_for(provider, "create_listing", "invalid")["review"] is True
    adjusted = errors.policy_for(provider, "create_listing", "invalid", {"invalid": {"review": False, "notify": True}})
    assert (adjusted["review"], adjusted["notify"]) == (False, True)
    # Retries stay the provider's, and junk in the overrides is ignored.
    kept = errors.policy_for(provider, "create_listing", "unavailable", {"unavailable": {"notify": True, "retry": None, "succeed": "yes"}})
    assert kept["notify"] is True and kept["retry"]["backoff"] == [60.0] and kept["succeed"] is False
    # "*" adjusts only codes the provider doesn't name — and only where a policy exists at all.
    assert errors.policy_for(provider, "create_listing", "invalid", {"*": {"review": False}})["review"] is True
    assert errors.policy_for(provider, "create_listing", "weird", {"*": {"notify": True}}) is None


def test_the_context_gets_resume_and_seed_only_when_the_sdk_has_them():
    @dataclasses.dataclass
    class OldContext:  # what SDK 0.4.0's IntegrationContext accepts
        config: dict
        secret: str | None

    old = errors.build_context(OldContext, config={}, secret=None, resume={"a": 1}, idempotency_seed="s")
    assert old == OldContext(config={}, secret=None)
    new = errors.build_context(sdk.IntegrationContext, config={}, secret=None, logger=None, http=None, resume={"a": 1}, idempotency_seed="s")
    assert (new.resume, new.idempotency_seed) == ({"a": 1}, "s")


def test_event_subscriptions_alert_but_never_about_alert_delivery(db_session, shop):
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel
    from marvin.services.event_bus_service.event_bus_listener import IntegrationEventListener
    from marvin.services.event_bus_service.event_types import EventTypes

    listener = IntegrationEventListener(shop.gid)
    sub = {
        "integration_id": shop.integration.id,
        "name": "Shop",
        "provider": _Shop.slug,
        "config": {},
        "secret_ref": None,
        "action": "ping",
        "args": {},
    }
    alert_event = SimpleNamespace(
        event_type=EventTypes.integration_attention_needed, document_data=None, entity_id=None, entity_type=None, message=""
    )
    shop.provider.failures = [IntegrationError("token expired", code="auth")]

    listener.publish_to_subscribers(alert_event, [sub])  # delivering an alert: the failure is only logged
    assert db_session.query(IntegrationAlertModel).filter_by(group_id=shop.gid).count() == 0

    other = SimpleNamespace(event_type=EventTypes.entry_published, document_data=None, entity_id=None, entity_type=None, message="")
    shop.provider.failures = [IntegrationError("token expired", code="auth")]
    listener.publish_to_subscribers(other, [sub])
    (alert,) = db_session.query(IntegrationAlertModel).filter_by(group_id=shop.gid).all()
    assert alert.code == "auth" and alert.samples[0]["source"] == "subscription"
    assert _retries(db_session, shop) == []  # connection scope: no retry, no review


def test_the_catalog_carries_the_policy_table():
    from marvin.schemas.group.integration import IntegrationProviderInfo

    info = IntegrationProviderInfo(**_Shop().info())
    assert info.error_policy["provider"]["invalid"]["summary"] == "send to review"
    assert info.actions[0].error_policy["unavailable"]["retry"]["backoff"] == [60.0]


# ── API ─────────────────────────────────────────────────────────────────────────


def _controller(db_session, shop, *, admin=True):
    from marvin.routes.groups.integrations_controller import IntegrationsController

    ctrl = SimpleNamespace(
        session=db_session, group_id=shop.gid, user=SimpleNamespace(admin=admin, platform_role=None, id=None, get_workspace_role=lambda gid: None)
    )
    ctrl._get_or_404 = lambda iid: IntegrationsController._get_or_404(ctrl, iid)
    ctrl._provider_or_none = lambda slug: IntegrationsController._provider_or_none(ctrl, slug)
    return ctrl


def test_admins_save_overrides_for_declared_codes_only(db_session, shop):
    from fastapi import HTTPException

    from marvin.routes.groups.integrations_controller import IntegrationsController
    from marvin.schemas.group.integration import IntegrationErrorOverrides

    ctrl = _controller(db_session, shop)
    saved = IntegrationsController.set_error_overrides(
        ctrl, shop.integration.id, IntegrationErrorOverrides(overrides={"invalid": {"review": False}, "*": {"notify": True}})
    )
    assert saved.error_overrides == {"invalid": {"review": False}, "*": {"notify": True}}

    with pytest.raises(HTTPException) as unknown:
        IntegrationsController.set_error_overrides(ctrl, shop.integration.id, IntegrationErrorOverrides(overrides={"nope": {"review": True}}))
    assert unknown.value.status_code == 422
    with pytest.raises(HTTPException) as retry:
        IntegrationsController.set_error_overrides(ctrl, shop.integration.id, IntegrationErrorOverrides(overrides={"invalid": {"retry": True}}))
    assert retry.value.status_code == 422
    with pytest.raises(HTTPException) as forbidden:
        IntegrationsController.set_error_overrides(_controller(db_session, shop, admin=False), shop.integration.id, IntegrationErrorOverrides())
    assert forbidden.value.status_code == 403

    reset = IntegrationsController.set_error_overrides(ctrl, shop.integration.id, IntegrationErrorOverrides(overrides={}))
    assert reset.error_overrides == {}


def test_resolve_endpoint_and_the_list_shows_attention(db_session, shop):
    from marvin.routes.groups.integrations_controller import IntegrationsController

    errors.notify(
        db_session, shop.gid, integration_id=shop.integration.id, integration_slug="shop", provider=_Shop.slug, code="auth", message="token expired"
    )
    ctrl = _controller(db_session, shop)

    (listed,) = IntegrationsController.list_integrations(ctrl)
    assert [a.code for a in listed.attention] == ["auth"] and listed.attention[0].message == "token expired"

    assert IntegrationsController.resolve_attention(ctrl, shop.integration.id).resolved == 1
    (listed,) = IntegrationsController.list_integrations(ctrl)
    assert listed.attention == []


def test_credentials_and_secret_args_never_leave_in_an_error(db_session, shop, monkeypatch):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform import Entries

    store = {"INTEGRATION_SHOP": "tok-secret-123", "API_KEY": "argsecret-456"}
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: store.get(ref))
    db_session.get(IntegrationModel, shop.integration.id).secret_ref = "INTEGRATION_SHOP"
    automation = db_session.query(WorkspaceAutomationModel).filter_by(group_id=shop.gid).one()
    step = {**WORKFLOW["actions"][0], "args": {"key": "{{API_KEY}}"}}
    automation.definition = {**WORKFLOW, "actions": [step]}
    db_session.commit()
    shop.provider.failures = [IntegrationError("rejected tok-secret-123 with key argsecret-456", code="invalid")]
    _Shop.error_policy = {**_Shop.error_policy, "invalid": Handle(review=True, notify=True)}
    try:
        _publish(db_session, shop)
    finally:
        _Shop.error_policy = {**_Shop.error_policy, "invalid": Handle(review=True)}

    entry = db_session.get(Entries, shop.entry_id)
    assert entry.metadata_json["integration_error"]["shop"]["message"] == "rejected [redacted] with key [redacted]"
    assert entry.metadata_json["review_reasons"] == ["Policy Shop · invalid — rejected [redacted] with key [redacted]"]
    (alert,) = db_session.query(IntegrationAlertModel).filter_by(group_id=shop.gid).all()
    assert "secret" not in alert.message and "[redacted]" in alert.message
