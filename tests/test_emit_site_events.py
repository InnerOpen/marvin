"""Workflows can turn a host's build notification into Marvin's own site build/deploy event."""

import uuid

import pytest

from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.emit_event import run_emit_event
from marvin.services.automation.authz import ROLE_ADMIN


@pytest.fixture
def dispatched(monkeypatch):
    calls = []

    class _Bus:
        def __init__(self, *a, **k):
            pass

        def dispatch(self, **kw):
            calls.append(kw)

    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _Bus)
    return calls


def test_a_failed_deploy_carries_its_message_and_reason(dispatched):
    ctx = {"event": {"payload": {"text": "Deployment failed for gmf", "data": {"reason": "Build exited 1"}}}, "depth": 0}
    action = {"kind": "emit_event", "event": "site_deployment_failed", "message": "${event.payload.text}", "error": "${event.payload.data.reason}"}

    out = run_emit_event(None, uuid.uuid4(), action, ctx, authorizer_role=ROLE_ADMIN)

    (call,) = dispatched
    assert out["emitted"] == "site_deployment_failed" and call["message"] == "Deployment failed for gmf"
    assert call["document_data"].status == "failed" and call["document_data"].error_message == "Build exited 1"


def test_a_site_event_needs_no_entry(dispatched):
    run_emit_event(None, uuid.uuid4(), {"kind": "emit_event", "event": "site_build_completed"}, {"event": {}, "depth": 0}, authorizer_role=ROLE_ADMIN)
    assert dispatched[0]["message"] == "Site build completed"


def test_other_event_families_are_refused():
    with pytest.raises(AutomationActionError, match="supports entry_"):
        run_emit_event(None, uuid.uuid4(), {"kind": "emit_event", "event": "user_signup"}, {"event": {}, "depth": 0}, authorizer_role=ROLE_ADMIN)


def test_the_feed_shows_a_deploy_failure_reason():
    from marvin.routes.platform.events_controller import _detail

    assert _detail({"documentData": {"errorMessage": "Build exited 1"}}) == "Build exited 1"
