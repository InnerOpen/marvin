"""Integration-owned error handling, core side: the engine applies a failed integration step's error
policy — review, retry, notify, carry on — and the retry sweep resumes the run at the failed step.

These tests drive the real engine and database with a stand-in step dispatcher that raises the
IntegrationStepError the integration executor would raise (policy already resolved), so they don't
need the integrations SDK. The SDK-backed half (the executor resolving a provider's declared policy,
ctx.resume / idempotency_seed, per-connection overrides) is in test_integration_error_policy_sdk.py.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pytest import fixture

from marvin.services.automation.actions.base import IntegrationStepError
from marvin.services.automation.engine import run_automations_for_event, run_retry
from marvin.services.automation.recorder import ExecutionRecorder
from marvin.services.integrations import errors

PREP = {"kind": "webhook", "id": "prep", "url": "https://example.test/prep"}
LIST = {"kind": "integration", "id": "list", "integration": "shop", "action": "create_listing", "args": {}}
AFTER = {"kind": "webhook", "id": "after", "url": "https://example.test/after"}


def _workflow(**extra) -> dict:
    return {
        "trigger": {"type": "event", "event": "entry_published"},
        "conditions": [{"field": "entry.data.sell", "op": "eq", "value": True}],
        "actions": [PREP, LIST, AFTER],
        **extra,
    }


def _handle(*, review=False, notify=False, succeed=False, retry=None, then=None) -> dict:
    """The shape of the SDK's Handle.to_dict()."""
    return {"review": review, "notify": notify, "succeed": succeed, "retry": retry, "then": then, "summary": "test policy"}


def _retry(*backoff, max_attempts=None, on_recovery=False) -> dict:
    return {"backoff": list(backoff), "max_attempts": max_attempts or max(len(backoff), 1), "on_recovery": on_recovery}


class _Runner:
    """Stands in for the step registry: webhooks succeed, the integration step raises the queued errors."""

    def __init__(self, integration_id, *failures):
        self.integration_id = integration_id
        self.failures = list(failures)
        self.calls: list[tuple[str, dict]] = []

    def fail(self, code="invalid", policy=None, *, partial=None, detail="the shop said no", retry_after=None):
        return IntegrationStepError(
            f"fake_shop.create_listing failed: {detail}",
            code=code,
            detail=detail,
            integration_id=self.integration_id,
            integration_slug="shop",
            provider="fake_shop",
            provider_name="Fake Shop",
            action_key="create_listing",
            policy=policy,
            partial=partial,
            retry_after=retry_after,
            seed="seed-1",
        )

    def __call__(self, session, group_id, action, context, **kw):
        self.calls.append((action["id"], dict(context.get("_resume") or {})))
        if action["kind"] == "integration" and self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        return {"ok": action["id"]}


@fixture
def events(monkeypatch):
    sent = []

    def dispatch(self, integration_id, group_id, event_type, document_data, message="", **kw):
        sent.append(SimpleNamespace(event_type=event_type, name=event_type.name, data=document_data, message=message))

    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService.dispatch", dispatch)
    return sent


@fixture
def shop(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"errs-{marker}", slug=f"errs-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    integration = IntegrationModel(session=db_session, group_id=gid, provider="fake_shop", name="Shop", slug="shop", enabled=True, config={})
    db_session.add(integration)
    automation = WorkspaceAutomationModel(session=db_session, group_id=gid, name="List it", slug="list-it", enabled=True, definition=_workflow())
    db_session.add(automation)
    et = EntryTypes(session=db_session, group_id=gid, name="Product", slug="product", schema_json={"fields": []})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    entry = Entries(
        session=db_session, group_id=gid, entry_type_id=et.id, title="Mug", slug=f"mug-{marker}", data_json={"sell": True}, status="draft"
    )
    db_session.add(entry)
    db_session.commit()
    yield SimpleNamespace(gid=gid, integration=integration, automation=automation, entry_id=entry.id)

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


def _publish(db_session, shop, runner):
    event = {
        "event_type": "entry_published",
        "entry_id": str(shop.entry_id),
        "user_id": None,
        "entity_type": "entry",
        "entity_id": str(shop.entry_id),
    }
    run_automations_for_event(db_session, shop.gid, event, run_action=runner, recorder=ExecutionRecorder(db_session, shop.gid))
    db_session.expire_all()


def _runs(db_session, shop):
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    return db_session.query(AutomationExecutionModel).filter_by(group_id=shop.gid).order_by(AutomationExecutionModel.started_at).all()


def _retries(db_session, shop):
    from marvin.db.models.groups.integration_errors import IntegrationRetryModel

    return db_session.query(IntegrationRetryModel).filter_by(group_id=shop.gid).all()


def _alerts(db_session, shop):
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel

    return db_session.query(IntegrationAlertModel).filter_by(group_id=shop.gid).all()


def _entry(db_session, shop):
    from marvin.db.models.platform import Entries

    return db_session.get(Entries, shop.entry_id)


def _retry_now(db_session, shop, runner):
    """Make the shop's pending retry due, claim it like the sweep does, and run it."""
    (row,) = [r for r in _retries(db_session, shop) if r.status == "pending"]
    row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    (claimed,) = errors.claim_due(db_session)
    outcome = run_retry(db_session, shop.gid, claimed, run_action=runner, recorder=ExecutionRecorder(db_session, shop.gid))
    db_session.expire_all()
    return outcome


def _failed_events(events):
    return [e for e in events if e.name == "automation_failed"]


# ── no policy: exactly today's behaviour ────────────────────────────────────────


def test_without_a_policy_the_step_fails_as_before(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail(policy=None)]

    _publish(db_session, shop, runner)

    (run,) = _runs(db_session, shop)
    assert run.status == "partial" and run.handled is False
    assert [c[0] for c in runner.calls] == ["prep", "list"]
    assert _retries(db_session, shop) == [] and _alerts(db_session, shop) == []
    assert _entry(db_session, shop).status == "draft"
    (failed,) = _failed_events(events)
    assert failed.data.handled is False and "handled by" not in failed.message


# ── immediate effects ───────────────────────────────────────────────────────────


def test_review_policy_sends_a_draft_to_review_and_says_why(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("invalid", _handle(review=True), detail="price must be positive")]

    _publish(db_session, shop, runner)

    entry = _entry(db_session, shop)
    assert entry.status == "needs_review"
    assert entry.metadata_json["review_reasons"] == ["Fake Shop · invalid — price must be positive"]
    note = entry.metadata_json["integration_error"]["shop"]
    assert (note["provider_name"], note["code"], note["message"], note["workflow"]) == ("Fake Shop", "invalid", "price must be positive", "list-it")
    (run,) = _runs(db_session, shop)
    assert run.status == "partial" and run.handled is True
    failed_step = next(a for a in run.actions if a.status == "failed")
    assert failed_step.handling["applied"] == ["review"]
    assert failed_step.handling["summary"] == "handled by Fake Shop: sent to review"
    (failed,) = _failed_events(events)
    assert failed.data.handled is True
    assert failed.data.handling == ["handled by Fake Shop: sent to review"]
    assert failed.message.endswith("— handled by Fake Shop: sent to review")


def test_review_never_unpublishes_a_live_entry_it_flags_it_and_alerts(db_session, shop, events):
    entry = _entry(db_session, shop)
    entry.status = "published"
    db_session.commit()
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("invalid", _handle(review=True), detail="price must be positive")]

    _publish(db_session, shop, runner)

    entry = _entry(db_session, shop)
    assert entry.status == "published"  # still on the site
    assert entry.metadata_json["review_reasons"] == ["Fake Shop · invalid — price must be positive"]
    assert entry.metadata_json["integration_error"]["shop"]["code"] == "invalid"
    (alert,) = _alerts(db_session, shop)  # a person still hears about it
    assert alert.code == "invalid"
    (run,) = _runs(db_session, shop)
    step = next(a for a in run.actions if a.status == "failed")
    assert step.handling["applied"] == ["flagged", "notify"]
    assert step.handling["summary"] == "handled by Fake Shop: flagged on the entry (left published), admins notified"


def test_succeed_policy_lets_the_pipeline_carry_on(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("not_found", _handle(succeed=True))]

    _publish(db_session, shop, runner)

    assert [c[0] for c in runner.calls] == ["prep", "list", "after"]
    (run,) = _runs(db_session, shop)
    assert run.status == "success"
    step = next(a for a in run.actions if a.label == "shop.create_listing")
    assert step.status == "success" and step.output_snapshot["ignored"] is True and step.output_snapshot["code"] == "not_found"
    assert [e.name for e in events if e.name.startswith("automation_")][-1] == "automation_ran"


def test_review_with_no_entry_notifies_admins_instead(db_session, shop, events):
    from marvin.services.automation.engine import run_automation_now

    shop.automation.definition = {**_workflow(), "trigger": {"type": "manual"}, "conditions": []}
    db_session.commit()
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("invalid", _handle(review=True))]

    run_automation_now(db_session, shop.gid, shop.automation, run_action=runner, recorder=ExecutionRecorder(db_session, shop.gid))

    (alert,) = _alerts(db_session, shop)
    assert alert.code == "invalid" and alert.status == "open"


# ── the workflow's own handling wins ────────────────────────────────────────────


def test_on_failure_steps_run_instead_of_the_policy_but_the_connection_alert_fires(db_session, shop, events):
    shop.automation.definition = _workflow(on_failure=[{"kind": "webhook", "id": "flag", "url": "https://example.test/flag"}])
    db_session.commit()
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("auth", _handle(review=True, notify=True, retry=_retry(60)))]

    _publish(db_session, shop, runner)

    assert [c[0] for c in runner.calls] == ["prep", "list", "flag"]
    assert _entry(db_session, shop).status == "draft"  # no review from the policy
    assert _retries(db_session, shop) == []  # no retry either
    (alert,) = _alerts(db_session, shop)
    assert alert.code == "auth"
    (run,) = _runs(db_session, shop)
    assert run.handled is False
    assert [e.name for e in events].count("integration_attention_needed") == 1


def test_a_workflow_can_opt_out_of_provider_policies(db_session, shop, events):
    shop.automation.definition = _workflow(integration_errors="fail")
    db_session.commit()
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("auth", _handle(review=True, notify=True))]

    _publish(db_session, shop, runner)

    assert _entry(db_session, shop).status == "draft"
    assert [a.code for a in _alerts(db_session, shop)] == ["auth"]


def test_integration_errors_is_validated_with_the_definition():
    from marvin.services.automation.validation import structural_issues

    assert structural_issues(_workflow(integration_errors="fail")) == []
    assert structural_issues(_workflow(integration_errors="policy")) == []
    (issue,) = structural_issues(_workflow(integration_errors="ignore"))
    assert "integration_errors" in issue["message"]


# ── retries ─────────────────────────────────────────────────────────────────────


def test_retry_resumes_at_the_failed_step_with_its_partial_progress(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(120, 600)), partial={"item_id": "I1"}), None]

    _publish(db_session, shop, runner)

    (row,) = _retries(db_session, shop)
    assert (row.status, row.attempt, row.max_attempts, row.code) == ("pending", 0, 2, "unavailable")
    assert row.partial == {"item_id": "I1"} and row.idempotency_seed == "seed-1"
    due_in = (errors._aware(row.next_attempt_at) - datetime.now(UTC)).total_seconds()
    assert 100 < due_in <= 120
    assert row.snapshot["steps"]["prep"] == {"output": {"ok": "prep"}}
    (first,) = _runs(db_session, shop)
    assert first.handled is True
    assert next(a for a in first.actions if a.status == "failed").handling["summary"] == "handled by Fake Shop: retry 1 of 2 scheduled"

    runner.calls.clear()
    assert _retry_now(db_session, shop, runner) == "succeeded"

    # The earlier step never runs again; the failed one gets its chain's progress and seed.
    assert [c[0] for c in runner.calls] == ["list", "after"]
    resume = runner.calls[0][1]
    assert resume["partial"] == {"item_id": "I1"} and resume["seed"] == "seed-1"
    (row,) = _retries(db_session, shop)
    assert row.status == "succeeded" and row.live_key is None
    original, retry = _runs(db_session, shop)
    assert retry.retry_of_id == original.id and retry.status == "success"
    ran = [e for e in events if e.name == "automation_ran"][-1]
    assert ran.data.retry_attempt == 1 and "succeeded on retry 1" in ran.message


def test_a_retry_that_fails_again_backs_off_then_applies_then(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    policy = _handle(retry=_retry(60, max_attempts=2), then=_handle(review=True))
    runner.failures = [runner.fail("unavailable", policy, retry_after=300), runner.fail("unavailable", policy), runner.fail("unavailable", policy)]

    _publish(db_session, shop, runner)
    (row,) = _retries(db_session, shop)
    assert (errors._aware(row.next_attempt_at) - datetime.now(UTC)).total_seconds() > 250  # the remote's retry_after wins

    assert _retry_now(db_session, shop, runner) == "failed"
    (row,) = _retries(db_session, shop)
    assert (row.status, row.attempt) == ("pending", 1)
    assert _entry(db_session, shop).status == "draft"

    assert _retry_now(db_session, shop, runner) == "failed"
    (row,) = _retries(db_session, shop)
    assert row.status == "exhausted"
    assert _entry(db_session, shop).status == "needs_review"
    last = _runs(db_session, shop)[-1]
    assert next(a for a in last.actions if a.status == "failed").handling["summary"] == "handled by Fake Shop: retries used up, sent to review"


def test_a_retry_is_superseded_when_the_entry_no_longer_matches(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60)))]
    _publish(db_session, shop, runner)

    entry = _entry(db_session, shop)
    entry.data_json = {"sell": False}  # taken off sale meanwhile: don't create the listing after all
    db_session.commit()
    runner.calls.clear()

    assert _retry_now(db_session, shop, runner) == "superseded"
    assert runner.calls == []
    (row,) = _retries(db_session, shop)
    assert row.status == "superseded" and "no longer matches" in row.last_error


def test_a_fresh_run_that_passes_the_step_supersedes_the_pending_retry(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60))), None]
    _publish(db_session, shop, runner)
    _publish(db_session, shop, runner)

    (row,) = _retries(db_session, shop)
    assert row.status == "superseded"


def test_a_fresh_failure_keeps_the_pending_retrys_schedule(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    policy = _handle(retry=_retry(600, 3600))
    runner.failures = [runner.fail("unavailable", policy), runner.fail("unavailable", policy)]
    _publish(db_session, shop, runner)
    (row,) = _retries(db_session, shop)
    due = row.next_attempt_at

    _publish(db_session, shop, runner)

    (row,) = _retries(db_session, shop)
    assert row.status == "pending" and row.attempt == 0 and row.next_attempt_at == due


def test_the_review_note_is_cleared_once_the_step_works(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("invalid", _handle(review=True)), None]
    _publish(db_session, shop, runner)
    _publish(db_session, shop, runner)

    assert "integration_error" not in (_entry(db_session, shop).metadata_json or {})


def test_retry_rows_are_pruned_after_30_days(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60))), None]
    _publish(db_session, shop, runner)
    _publish(db_session, shop, runner)  # supersedes it
    (row,) = _retries(db_session, shop)
    row.finished_at = datetime.now(UTC) - timedelta(days=31)
    db_session.commit()

    assert errors.prune(db_session) >= 1
    assert _retries(db_session, shop) == []


# ── alerts ──────────────────────────────────────────────────────────────────────


def test_alerts_dedupe_per_connection_and_code_and_remind_after_the_window(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    policy = _handle(notify=True)
    runner.failures = [runner.fail("auth", policy), runner.fail("auth", policy, detail="still expired"), runner.fail("auth", policy)]

    _publish(db_session, shop, runner)
    _publish(db_session, shop, runner)

    (alert,) = _alerts(db_session, shop)
    assert (alert.count, alert.message, len(alert.samples)) == (2, "still expired", 2)
    needed = [e for e in events if e.name == "integration_attention_needed"]
    assert len(needed) == 1 and needed[0].data.reminder is False
    assert needed[0].data.title == "fake_shop needs attention"  # the provider isn't installed here: its key stands in

    alert.notified_at = datetime.now(UTC) - timedelta(hours=25)
    db_session.commit()
    _publish(db_session, shop, runner)

    needed = [e for e in events if e.name == "integration_attention_needed"]
    assert len(needed) == 2 and needed[1].data.reminder is True and needed[1].data.count == 3


def test_resolving_rearms_parked_retries_and_goes_back_through_the_alerts_channels(db_session, shop, events):
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
    from marvin.db.models.groups.email_templates import EmailTemplateModel

    template = EmailTemplateModel(
        session=db_session, group_id=shop.gid, name="Alert", template_type="custom", subject="{{title}}", body_markdown="{{summary}}"
    )
    db_session.add(template)
    db_session.flush()
    route = EmailEventSubscriptionModel(
        session=db_session, group_id=shop.gid, template_id=template.id, event_type=errors.NEEDED, recipient_type="admins", enabled=True
    )
    db_session.add(route)
    db_session.commit()
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("auth", _handle(notify=True, retry=_retry(on_recovery=True)))]

    _publish(db_session, shop, runner)

    (row,) = _retries(db_session, shop)
    assert row.status == "parked" and row.next_attempt_at is None
    (alert,) = _alerts(db_session, shop)
    assert alert.channels == {"email": [str(route.id)], "integration": []}

    route.enabled = False  # the routing changed in between — the resolved notice still goes there
    db_session.commit()
    assert errors.resolve_alerts(db_session, shop.gid, shop.integration.id, resolution="manual") == 1

    db_session.expire_all()
    (row,) = _retries(db_session, shop)
    assert row.status == "pending" and row.next_attempt_at is not None
    resolved = next(e for e in events if e.name == "integration_attention_resolved")
    assert resolved.data.channels == {"email": [str(route.id)], "integration": []}
    assert "working again" in resolved.data.summary
    delivered = errors.resolved_channel_rows(
        db_session, shop.gid, SimpleNamespace(event_type=resolved.event_type, document_data=resolved.data), EmailEventSubscriptionModel, "email"
    )
    assert [r.id for r in delivered] == [route.id]
    db_session.query(EmailEventSubscriptionModel).filter_by(group_id=shop.gid).delete()
    db_session.query(EmailTemplateModel).filter_by(group_id=shop.gid).delete()
    db_session.commit()


def test_a_successful_action_resolves_the_connections_alerts(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("auth", _handle(notify=True))]
    _publish(db_session, shop, runner)

    assert errors.connection_succeeded(shop.gid, shop.integration.id, session=db_session) == 1

    (alert,) = _alerts(db_session, shop)
    assert (alert.status, alert.resolution, alert.open_key) == ("resolved", "action", None)


def test_delivering_an_alert_never_opens_another(db_session, shop, events):
    token = errors._delivering_alert.set(True)
    try:
        assert (
            errors.notify(
                db_session, shop.gid, integration_id=shop.integration.id, integration_slug="shop", provider="fake_shop", code="auth", message="x"
            )
            is None
        )
    finally:
        errors._delivering_alert.reset(token)
    assert _alerts(db_session, shop) == []


# ── alert routing ───────────────────────────────────────────────────────────────


def test_routing_writes_subscription_rows_and_disables_rather_than_deletes(db_session, shop, monkeypatch):
    from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
    from marvin.db.models.groups.email_templates import EmailTemplateModel
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.services.integrations import alert_routing

    template = EmailTemplateModel(
        session=db_session, group_id=None, name="Integration Alert", template_type="integration_alert", subject="{{title}}", body_markdown="x"
    )
    prefs = GroupPreferencesModel(session=db_session, group_id=shop.gid)
    db_session.add_all([template, prefs])
    db_session.commit()
    monkeypatch.setattr(alert_routing, "_system_template_id", lambda session: template.id)
    try:
        routing = alert_routing.set_routing(db_session, shop.gid, email_admins=True, integration_ids=[], reminder_hours=6)
        assert routing["email_admins"] is True and routing["reminder_hours"] == 6
        (row,) = db_session.query(EmailEventSubscriptionModel).filter_by(group_id=shop.gid).all()
        assert (row.event_type, row.recipient_type, row.enabled) == (errors.NEEDED, "admins", True)

        routing = alert_routing.set_routing(db_session, shop.gid, email_admins=False, integration_ids=[], reminder_hours=0)
        assert routing["email_admins"] is False
        (row,) = db_session.query(EmailEventSubscriptionModel).filter_by(group_id=shop.gid).all()
        assert row.enabled is False  # kept: an open alert's resolved notice may still need it
        assert errors._reminder_hours(db_session, shop.gid) == 0

        with pytest.raises(ValueError):
            alert_routing.set_routing(db_session, shop.gid, email_admins=False, integration_ids=[shop.integration.id], reminder_hours=24)
    finally:
        db_session.rollback()
        db_session.query(EmailEventSubscriptionModel).filter_by(group_id=shop.gid).delete()
        db_session.query(EmailTemplateModel).filter_by(id=template.id).delete()
        db_session.commit()


# ── run history message ─────────────────────────────────────────────────────────


def test_run_message_names_the_handling_and_the_retry():
    from marvin.services.automation.summary import run_handled, run_message

    failed = {"kind": "integration", "target": "shop.create_listing", "outcome": "failed", "ok": False, "error": "nope", "count": 1}
    handled = {**failed, "handling": "handled by Square: sent to review", "handled": True}
    assert run_message("w", False, [handled]) == "Automation 'w' failed — integration 'shop.create_listing': nope — handled by Square: sent to review"
    assert run_handled([handled]) is True and run_handled([failed]) is False
    ok = {"kind": "integration", "target": "shop.create_listing", "outcome": "ok", "ok": True, "error": None, "count": 1}
    assert run_message("w", True, [ok], retry_attempt=2).startswith("Automation 'w' succeeded on retry 2 — ")


def test_retry_rows_keep_no_entry_foreign_key_and_both_tables_index_created_at(db_session):
    from sqlalchemy import inspect

    inspector = inspect(db_session.bind)
    assert not [fk for fk in inspector.get_foreign_keys("integration_retries") if fk["referred_table"] == "entries"]
    for table in ("integration_retries", "integration_alerts"):
        assert f"ix_{table}_created_at" in {index["name"] for index in inspector.get_indexes(table)}


def test_alternating_codes_share_one_retry_budget_then_review_and_notify(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    a = _handle(retry=_retry(60, 60, 60))  # 3 retries
    b = _handle(retry=_retry(60, 60))  # 2 retries
    runner.failures = [
        runner.fail("unavailable", a),
        runner.fail("rate_limited", b),
        runner.fail("unavailable", a),
        runner.fail("rate_limited", b),
    ]
    _publish(db_session, shop, runner)

    assert _retry_now(db_session, shop, runner) == "failed"  # retry 1 fails differently: the budget carries on
    (row,) = _retries(db_session, shop)
    assert (row.status, row.attempt, row.max_attempts, row.code) == ("pending", 1, 3, "rate_limited")
    assert _retry_now(db_session, shop, runner) == "failed"
    (row,) = _retries(db_session, shop)
    assert (row.status, row.attempt) == ("pending", 2)
    assert _retry_now(db_session, shop, runner) == "failed"

    (row,) = _retries(db_session, shop)
    assert row.status == "exhausted" and row.codes == ["rate_limited", "unavailable"]
    # Neither code declares a `then`, but the chain mixed codes: review + notify, so it can't end silently.
    assert _entry(db_session, shop).status == "needs_review"
    assert [a.code for a in _alerts(db_session, shop)] == ["rate_limited"]


def test_a_fresh_failure_with_another_code_keeps_the_chains_attempts(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60, 60, 60))), runner.fail("unavailable", _handle(retry=_retry(60, 60, 60)))]
    _publish(db_session, shop, runner)
    _retry_now(db_session, shop, runner)
    runner.failures = [runner.fail("rate_limited", _handle(retry=_retry(60)))]

    _publish(db_session, shop, runner)

    (row,) = _retries(db_session, shop)
    assert (row.status, row.attempt, row.code, row.max_attempts) == ("pending", 1, "rate_limited", 3)


def test_a_chain_older_than_24_hours_ends(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    policy = _handle(retry=_retry(60, max_attempts=10))
    runner.failures = [runner.fail("unavailable", policy), runner.fail("unavailable", policy)]
    _publish(db_session, shop, runner)
    (row,) = _retries(db_session, shop)
    row.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=25)
    db_session.commit()

    assert _retry_now(db_session, shop, runner) == "failed"

    (row,) = _retries(db_session, shop)
    assert row.status == "exhausted" and row.attempt == 1
    assert _entry(db_session, shop).status == "needs_review"  # timed out without a `then`: review + notify
    assert [a.code for a in _alerts(db_session, shop)] == ["unavailable"]


def test_succeed_with_retry_ignores_the_retry(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("not_found", _handle(succeed=True, retry=_retry(60)))]

    _publish(db_session, shop, runner)

    assert [c[0] for c in runner.calls] == ["prep", "list", "after"]
    assert _retries(db_session, shop) == []  # retrying would run "after" a second time


def test_a_retry_outlives_its_deleted_entry(db_session, shop, events):
    from marvin.db.models.platform import Entries

    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60))), None]
    _publish(db_session, shop, runner)
    db_session.query(Entries).filter(Entries.id == shop.entry_id).delete()
    db_session.commit()
    (row,) = _retries(db_session, shop)
    assert row.status == "pending"  # no cascade: the retry is still there
    runner.calls.clear()

    assert _retry_now(db_session, shop, runner) == "succeeded"  # the snapshot's entry stands in
    assert [c[0] for c in runner.calls] == ["list", "after"]


def test_an_entry_deleted_run_can_be_retried(db_session, shop, events):
    shop.automation.definition = {**_workflow(), "trigger": {"type": "event", "event": "entry_deleted"}, "conditions": []}
    db_session.commit()
    gone = str(uuid.uuid4())  # the entry no longer exists when the workflow runs
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60))), None]
    event = {"event_type": "entry_deleted", "entry_id": gone, "user_id": None}
    run_automations_for_event(db_session, shop.gid, event, run_action=runner, recorder=ExecutionRecorder(db_session, shop.gid))
    db_session.expire_all()

    (row,) = _retries(db_session, shop)
    assert str(row.entry_id) == gone and row.status == "pending"
    assert _retry_now(db_session, shop, runner) == "succeeded"


def test_retries_of_a_disabled_workflow_wait_for_it(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60))), None]
    _publish(db_session, shop, runner)
    (row,) = _retries(db_session, shop)
    row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    shop.automation.enabled = False
    db_session.commit()

    assert errors.claim_due(db_session) == []
    (row,) = _retries(db_session, shop)
    assert (row.status, row.attempt) == ("pending", 0)

    shop.automation.enabled = True
    db_session.commit()
    assert _retry_now(db_session, shop, runner) == "succeeded"


def test_a_reclaimed_lease_counts_as_an_attempt(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60)))]
    _publish(db_session, shop, runner)
    (row,) = _retries(db_session, shop)
    row.status, row.attempt, row.lease_until = "running", 1, datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    (claimed,) = errors.claim_due(db_session)

    assert claimed.attempt == 2 and claimed.attempt > claimed.max_attempts  # the sweep ends it instead of running it


def test_plain_failures_that_run_out_apply_then_or_notify(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60)))]
    _publish(db_session, shop, runner)
    (row,) = _retries(db_session, shop)
    row.attempt = row.max_attempts
    db_session.commit()

    errors.retry_failed_plainly(db_session, row, "integration 'shop' is disabled")

    db_session.expire_all()
    (row,) = _retries(db_session, shop)
    assert row.status == "exhausted"
    (alert,) = _alerts(db_session, shop)  # no `then`: admins are told
    assert alert.message == "integration 'shop' is disabled"


def test_attempts_are_at_least_a_minute_apart(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("auth", _handle(retry=_retry(on_recovery=True)))]  # empty backoff, no alert to park on

    _publish(db_session, shop, runner)

    (row,) = _retries(db_session, shop)
    assert row.status == "pending"
    assert (errors._aware(row.next_attempt_at) - datetime.now(UTC)).total_seconds() > 55


def test_parked_retries_without_an_open_alert_go_back_to_pending(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("auth", _handle(notify=True, retry=_retry(on_recovery=True)))]
    _publish(db_session, shop, runner)
    (alert,) = _alerts(db_session, shop)
    alert.status, alert.open_key = "resolved", None  # resolved between the failure and the parking
    db_session.commit()

    assert errors.rearm_orphaned_parked(db_session) == 1
    (row,) = _retries(db_session, shop)
    assert row.status == "pending"


def test_the_sweep_runs_off_the_event_loop_within_a_time_budget(db_session, shop, events):
    import asyncio

    from marvin.services.scheduler.tasks.sweep_integration_retries import sweep_integration_retries, sweep_once

    assert asyncio.iscoroutinefunction(sweep_integration_retries)
    runner = _Runner(shop.integration.id)
    runner.failures = [runner.fail("unavailable", _handle(retry=_retry(60, 60)))]
    _publish(db_session, shop, runner)
    (row,) = _retries(db_session, shop)
    row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert sweep_once(budget_s=0) == {}  # out of time: the row waits for the next tick
    db_session.expire_all()
    assert _retries(db_session, shop)[0].attempt == 0

    sweep_once()  # the real step can't run here (no provider installed): counted as a plain failure
    db_session.expire_all()
    (row,) = _retries(db_session, shop)
    assert row.attempt == 1 and row.status == "pending"


def test_intermediate_retry_failures_are_not_announced(db_session, shop, events):
    runner = _Runner(shop.integration.id)
    policy = _handle(retry=_retry(60, max_attempts=2), then=_handle(review=True))
    runner.failures = [runner.fail("unavailable", policy), runner.fail("unavailable", policy), runner.fail("unavailable", policy)]
    _publish(db_session, shop, runner)
    assert len(_failed_events(events)) == 1  # the first failure of the chain

    _retry_now(db_session, shop, runner)  # fails again, next retry scheduled
    assert len(_failed_events(events)) == 1

    _retry_now(db_session, shop, runner)  # runs out: `then` applies
    failed = _failed_events(events)
    assert len(failed) == 2 and failed[-1].data.retry_attempt == 2 and failed[-1].data.handled is True


def test_secrets_are_redacted():
    secrets = errors.secret_values("tok-secret-123", "slack://a/b/c\nmailto://user:pass@example.com", None, "")
    text = "auth failed for tok-secret-123 via mailto://user:pass@example.com"
    assert errors.redact(text, secrets) == "auth failed for [redacted] via [redacted]"
