"""The Send an alert step (`alert`): a workflow alerts the workspace. The step records a `workflow_alert` event — the
bell shows it, its details behind More — and Notifications sends it where "Sent by a workflow" alerts go (email, push,
connected channels), details included. Title, message and details are templates (Variables too); a dry run sends nothing."""

# ruff: noqa: F811 — `ws` / `workspace` are fixtures, not redefinitions
from types import SimpleNamespace

import pytest

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.services import alerting, workspace_alerts
from marvin.services.automation.engine import run_automation_now
from marvin.services.automation.recorder import ExecutionRecorder
from tests.test_workflow_authoring import AD, _tool, gates, workspace, ws  # noqa: F401 — fixtures

ALERT = {"kind": "alert", "id": "ping", "title": "Stock low: ${input.item}", "message": "Only ${input.left} left."}


def _workflow(ws, step=ALERT):
    definition = {
        "trigger": {"type": "manual", "inputs": [{"name": "item", "type": "text"}, {"name": "left", "type": "number"}]},
        "actions": [step],
    }
    row = WorkspaceAutomationModel(session=ws.session, group_id=ws.gid, name="Stock", slug="stock", enabled=True, definition=definition)
    ws.session.add(row)
    ws.session.commit()
    return row


def _run(ws, row, dry_run=False):
    recorder = ExecutionRecorder(ws.session, ws.gid)
    return run_automation_now(
        ws.session, ws.gid, row, user_id=ws.uid, recorder=recorder, inputs={"item": "Brass lantern", "left": "2"}, dry_run=dry_run
    )


@pytest.fixture
def mailed(monkeypatch):
    """What the alert email channel was handed (no mail server)."""
    sent = []

    def send_email(scope, session, settings, message):
        sent.append(message)
        return alerting.Delivery(alerting.SENT, "Sent to the owners and admins")

    monkeypatch.setattr(alerting, "send_email", send_email)
    monkeypatch.setattr("marvin.services.web_push.configured", lambda: False)
    return sent


@pytest.fixture
def events(monkeypatch):
    """The events the step dispatched, as the listener would get them."""
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    seen = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: kw["event_type"].name == "workflow_alert" and seen.append(kw))
    return seen


def _delivered(ws, dispatched) -> dict:
    """Hand a dispatched event to the Notifications listener, as the event bus does."""
    event = SimpleNamespace(event_type=dispatched["event_type"], document_data=dispatched["document_data"], workspace_id=ws.gid)
    return workspace_alerts.deliver(ws.session, ws.gid, event)


def test_the_step_records_an_alert_event_with_its_details(ws, events):
    row = _workflow(ws, {**ALERT, "details": "${input.item}: reorder from the usual supplier"})

    result = _run(ws, row)

    assert result["ok"]
    (sent,) = events
    data = sent["document_data"]
    assert sent["event_type"].name == "workflow_alert" and sent["message"] == "Stock low: Brass lantern — Only 2 left."
    assert (data.title, data.message, data.details) == ("Stock low: Brass lantern", "Only 2 left.", "Brass lantern: reorder from the usual supplier")
    assert data.automation_id == row.id


def test_details_from_a_list_or_an_object_read_a_line_each(ws, events):
    _run(ws, _workflow(ws, {**ALERT, "details": {"item": "${input.item}", "left": "${input.left}"}}))

    assert events[0]["document_data"].details == "item: Brass lantern\nleft: 2"


def test_notifications_send_it_with_its_details_and_link(ws, events, mailed):
    row = _workflow(ws, {**ALERT, "details": "Ordered 14 this week."})
    _run(ws, row)

    _delivered(ws, events[0])

    (message,) = mailed
    assert (message.title, message.summary, message.detail) == ("Stock low: Brass lantern", "Only 2 left.", "Ordered 14 this week.")
    assert message.path == f"/automation/workflows?workflow={row.id}"  # the default link: this workflow's runs


def test_a_warning_or_an_error_says_so_ahead_of_the_title(ws, events, mailed):
    _run(ws, _workflow(ws, {**ALERT, "level": "error"}))

    _delivered(ws, events[0])

    assert events[0]["document_data"].level == "error"
    assert (mailed[0].title, mailed[0].summary) == ("Error: Stock low: Brass lantern", "Only 2 left.")


def test_an_info_alert_is_the_default_and_goes_as_written(ws, events, mailed):
    _run(ws, _workflow(ws))

    _delivered(ws, events[0])

    assert events[0]["document_data"].level == "info" and mailed[0].title == "Stock low: Brass lantern"


def test_a_web_address_link_is_kept_as_it_is(ws, events, mailed):
    _run(ws, _workflow(ws, {**ALERT, "link": "https://shop.test/restock"}))

    _delivered(ws, events[0])

    assert mailed[0].link == "https://shop.test/restock"


def test_nothing_is_sent_on_while_workflow_alerts_are_off(ws, events, mailed):
    settings = workspace_alerts.load(ws.session, ws.gid)
    settings.types[workspace_alerts.WORKFLOW_ALERT] = False
    alerting.save(workspace_alerts.WorkspaceScope(ws.gid), ws.session, settings)
    _run(ws, _workflow(ws))

    assert _delivered(ws, events[0]) == {} and mailed == []


def test_a_link_that_is_neither_a_page_nor_a_web_address_fails_the_step(ws, events):
    result = _run(ws, _workflow(ws, {**ALERT, "link": "javascript:alert(1)"}))

    assert not result["ok"] and events == []


def test_send_once_sends_a_key_once_within_its_window(ws, events):
    row = _workflow(ws, {**ALERT, "idempotency_key": "low-${input.item}", "idempotency_window_hours": 48})

    first, second = _run(ws, row), _run(ws, row)

    assert first["ok"] and second["ok"] and len(events) == 1


def test_a_dry_run_sends_nothing(ws, events):
    _run(ws, _workflow(ws), dry_run=True)

    assert events == []


def test_workflow_alerts_are_a_kind_the_notifications_page_lists():
    kind = workspace_alerts.KINDS_BY_KEY[workspace_alerts.WORKFLOW_ALERT]
    assert (kind.label, kind.event_type, kind.default) == ("Sent by a workflow", "workflow_alert", True)
