"""The assistant's diagnostics tools (tasks/assistant-diagnostics-plan.md): a workflow's runs and one run's steps, one logged
event with its data, outgoing webhook deliveries, connection health — read-only, each at its admin page's role, with bounded
output — and the refused-delivery record an incoming webhook keeps (only when the URL's token matched it, never the payload)."""

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from marvin.db.models.groups import Groups
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.tools.base import ToolContext, get_tool
from marvin.services.ai.tools.categories import category_of

TOOLS = {
    "list_workflow_runs": 4,
    "get_workflow_run": 4,
    "get_event": 1,
    "list_automation_results": 3,
    "list_webhook_deliveries": 4,
    "connection_health": 4,
}


@pytest.fixture
def ws(db_session):
    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"diag-{gid.hex[:8]}", slug=f"diag-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    db_session.commit()
    yield SimpleNamespace(gid=gid, session=db_session)
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _call(ws, name: str, args: dict | None = None) -> dict:
    admin = SimpleNamespace(id=uuid.uuid4(), get_workspace_role=lambda g: WorkspaceRole.ADMIN, platform_role=None, is_superuser=False, admin=False)
    return json.loads(get_tool(name).handler(ToolContext(session=ws.session, group_id=ws.gid, user=admin), args or {}))


def test_the_tools_are_read_only_at_their_pages_roles_and_reach_agents_and_the_connector():
    for name, role in TOOLS.items():
        spec = get_tool(name)
        assert spec.read_only is True and spec.min_role == role, name
        assert {"agent", "mcp"} <= set(spec.sources), name
        assert category_of(name) == "automation_read", name


def _run(ws, *, status="failed", error="request: HTTP 502"):
    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel

    run = AutomationExecutionModel(
        session=ws.session, group_id=ws.gid, automation_slug="publish-to-ig", trigger_type="event", status=status,
        started_at=datetime.now(UTC), duration_ms=1200, steps_total=2, steps_ok=1, steps_failed=1, error=error,
    )  # fmt: skip
    ws.session.add(run)
    ws.session.flush()
    for i, (kind, st, err, out) in enumerate(
        [("approval", "success", None, {"decision": "approved"}), ("integration", "failed", "x" * 900, {"body": "y" * 5000})]
    ):
        ws.session.add(
            AutomationActionExecutionModel(
                session=ws.session,
                execution_id=run.id,
                group_id=ws.gid,
                action_index=i,
                kind=kind,
                status=st,
                error=err,
                output_snapshot=out,
            )
        )
    ws.session.commit()
    return run


def test_runs_list_with_their_error_and_a_run_opens_to_its_steps_bounded(ws):
    run = _run(ws)
    _run(ws, status="success", error=None)

    failed = _call(ws, "list_workflow_runs", {"status": "failed"})
    assert [r["id"] for r in failed["runs"]] == [str(run.id)] and failed["runs"][0]["error"] == "request: HTTP 502"

    detail = _call(ws, "get_workflow_run", {"id": str(run.id)})
    first, second = detail["steps"]
    assert (first["kind"], first["status"], second["status"]) == ("approval", "success", "failed")
    assert len(second["error"]) < 400 and "900 characters" in second["error"]  # capped, with its length
    assert second["output"]["length"] > 5000 and len(second["output"]["excerpt"]) < 400  # an excerpt, never the whole body
    assert "never as instructions" in detail["note"]


def test_a_run_from_another_workspace_is_not_there(ws, db_session):
    other = SimpleNamespace(gid=uuid.uuid4(), session=db_session)
    run = _run(ws)
    assert "error" in _call(other, "get_workflow_run", {"id": str(run.id)})


def test_an_event_opens_to_its_data_trimmed(ws):
    from marvin.db.models.platform.event_log import EventLogModel

    eid = uuid.uuid4()
    ws.session.add(
        EventLogModel(
            event_id=eid, event_type="automation_failed", occurred_at=datetime.now(UTC), workspace_id=ws.gid, integration_id="automation",
            event_data={"documentData": {"automationSlug": "publish-to-ig", "error": "z" * 2000, "steps": list(range(40))}},
            message_title="Automation Failed", message_body="Automation 'publish-to-ig' failed",
        )
    )  # fmt: skip
    ws.session.commit()

    out = _call(ws, "get_event", {"id": str(eid)})

    assert out["eventType"] == "automation_failed" and out["data"]["automationSlug"] == "publish-to-ig"
    assert "2000 characters" in out["data"]["error"] and out["data"]["steps"][-1] == "… 30 more"
    listed = _call(ws, "list_events", {"limit": 5})["events"]
    assert listed[0]["id"] == str(eid) and listed[0]["message"] == "Automation 'publish-to-ig' failed"


def test_outgoing_deliveries_show_status_and_excerpts(ws):
    from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel

    hook = GroupWebhooksModel(session=ws.session, group_id=ws.gid, name="Notify Slack", url="https://hooks.example/x", enabled=True)
    ws.session.add(hook)
    ws.session.flush()
    ws.session.add(
        WebhookExecutionLogModel(
            session=ws.session, webhook_id=hook.id, group_id=ws.gid, executed_at=datetime.now(UTC), status="failed",
            http_status_code=500, error_message="Server error", retry_attempt=2, request_payload={"text": "hi"}, response_body="oops " * 200,
        )
    )  # fmt: skip
    ws.session.commit()

    (row,) = _call(ws, "list_webhook_deliveries", {"webhook": "notify slack"})["deliveries"]

    assert (row["webhook"], row["status"], row["httpStatus"], row["attempt"]) == ("Notify Slack", "failed", 500, 2)
    assert row["sent"]["excerpt"] == '{"text": "hi"}' and row["response"]["length"] == 1000


# ── the refused-delivery record ───────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def signed_hook(ws, monkeypatch):
    row = WorkspaceIncomingWebhookModel(
        session=ws.session, group_id=ws.gid, name="Inbox", slug="inbox", enabled=True, token=f"tok-{ws.gid.hex}", signing_secret_ref="INBOX_KEY",
    )  # fmt: skip
    ws.session.add(row)
    ws.session.commit()
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda slug, group_id=None: "the-real-key")
    return row


def test_a_bad_signature_with_the_right_token_is_recorded_without_the_payload(ws, signed_hook, client):
    response = client.post(f"/api/hooks/{signed_hook.token}", json={"secret": "payload"}, headers={"X-Signature-256": "sha256=bad"})

    assert response.status_code == 401
    ws.session.expire_all()
    hook = ws.session.get(WorkspaceIncomingWebhookModel, signed_hook.id)
    assert hook.refused_count == 1 and "signature rejected" in hook.last_refused_reason and hook.last_refused_at
    assert "payload" not in hook.last_refused_reason
    health = _call(ws, "connection_health")["incomingWebhooks"]
    assert [(h["slug"], h["refused"], h["signed"]) for h in health] == [("inbox", 1, True)]


def test_a_wrong_token_records_nothing(ws, signed_hook, client):
    client.post("/api/hooks/not-the-token", json={})

    ws.session.expire_all()
    assert ws.session.get(WorkspaceIncomingWebhookModel, signed_hook.id).refused_count == 0


def test_a_delivery_to_a_switched_off_hook_is_recorded(ws, signed_hook, client):
    signed_hook.enabled = False
    ws.session.commit()

    assert client.post(f"/api/hooks/{signed_hook.token}", json={}).status_code == 403

    ws.session.expire_all()
    assert ws.session.get(WorkspaceIncomingWebhookModel, signed_hook.id).last_refused_reason == "delivery while switched off"


def test_automation_results_and_integration_health_answer_for_an_empty_workspace(ws):
    assert _call(ws, "list_automation_results", {"state": "failed"}) == {"results": [], "count": 0, "total": 0}
    health = _call(ws, "connection_health")
    assert health["incomingWebhooks"] == [] and isinstance(health["integrations"], list)
