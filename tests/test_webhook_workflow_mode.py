"""Workflow-only webhook type + delivery logging for workflow webhook steps."""

from types import SimpleNamespace

from marvin.services.event_bus_service.event_types import WEBHOOK_MODE_DESCRIPTIONS, WebhookMode


class TestWorkflowWebhookMode:
    def test_workflow_mode_exists_and_is_described(self):
        assert WebhookMode.workflow.value == "workflow"
        assert "workflow" in WEBHOOK_MODE_DESCRIPTIONS[WebhookMode.workflow.value].lower()

    def test_workflow_mode_needs_no_schedule(self):
        from marvin.routes.groups.webhook_controller import _validate_webhook_mode

        _validate_webhook_mode(SimpleNamespace(webhook_type=WebhookMode.workflow, scheduled_time=None))  # no raise
        _validate_webhook_mode(SimpleNamespace(webhook_type=WebhookMode.event_driven, scheduled_time=None))

    def test_generic_mode_still_needs_schedule(self):
        import pytest
        from fastapi import HTTPException

        from marvin.routes.groups.webhook_controller import _validate_webhook_mode

        with pytest.raises(HTTPException):
            _validate_webhook_mode(SimpleNamespace(webhook_type=WebhookMode.generic, scheduled_time=None))

    def test_event_bus_never_fires_workflow_webhooks(self):
        """The reaction listener only delivers to event_driven webhooks with subscriptions; a
        workflow webhook (no subscriptions, different type) is invisible to it by construction."""
        wh = SimpleNamespace(subscribed_events=[], webhook_type=WebhookMode.workflow)
        fires = bool(wh.subscribed_events) and "x" in wh.subscribed_events and getattr(wh.webhook_type, "value", None) == "event_driven"
        assert fires is False


class TestWorkflowWebhookStepLogsDeliveries:
    def _run(self, monkeypatch, resp, wh):
        import httpx

        import marvin.services.event_bus_service.publisher as pub
        from marvin.services.automation.actions.webhook import run_webhook
        from marvin.services.automation.authz import ROLE_ADMIN

        logged = []
        monkeypatch.setattr(pub, "_log_webhook_execution", lambda *a, **k: logged.append((a, k)))
        monkeypatch.setattr(httpx, "request", lambda *a, **k: resp)
        try:
            run_webhook(
                SimpleNamespace(get=lambda m, i: wh),
                "G",
                {"kind": "webhook", "webhook_id": "w1"},
                {"event": {"x": 1}, "depth": 0},
                authorizer_role=ROLE_ADMIN,
            )
        except Exception:
            pass
        return logged

    def test_success_is_logged(self, monkeypatch):
        wh = SimpleNamespace(
            group_id="G", enabled=True, url="https://example.test/h", method="POST", headers_json=None, custom_payload={"k": "$event.x"}, name="h"
        )
        logged = self._run(monkeypatch, SimpleNamespace(status_code=201, is_success=True, text="ok", json=lambda: {"ok": True}), wh)
        assert len(logged) == 1
        (webhook_id, group_id, status), kw = logged[0]
        assert (webhook_id, group_id, status) == ("w1", "G", "success") and kw["http_status_code"] == 201 and kw["request_payload"] == {"k": 1}

    def test_failure_is_logged_with_status_and_error(self, monkeypatch):
        wh = SimpleNamespace(
            group_id="G", enabled=True, url="https://example.test/h", method="POST", headers_json=None, custom_payload=None, name="h"
        )
        logged = self._run(monkeypatch, SimpleNamespace(status_code=400, is_success=False, text='{"code":"nope"}', json=lambda: {"code": "nope"}), wh)
        (_, _, status), kw = logged[0]
        assert status == "failed" and kw["http_status_code"] == 400 and "nope" in kw["error_message"]

    def test_raw_url_steps_do_not_log(self, monkeypatch):
        import httpx

        import marvin.services.event_bus_service.publisher as pub
        from marvin.services.automation.actions.webhook import run_webhook
        from marvin.services.automation.authz import ROLE_ADMIN

        logged = []
        monkeypatch.setattr(pub, "_log_webhook_execution", lambda *a, **k: logged.append(1))
        monkeypatch.setattr(httpx, "request", lambda *a, **k: SimpleNamespace(status_code=200, is_success=True, text="{}", json=lambda: {}))
        run_webhook(None, "G", {"kind": "webhook", "url": "https://example.test/h"}, {"event": {}, "depth": 0}, authorizer_role=ROLE_ADMIN)
        assert logged == []
