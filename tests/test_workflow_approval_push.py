"""One-tap Approve / Deny on a waiting workflow run's push (services/push_actions.py, routes/users/push_controller.py):
each approver's push carries their own single-use token — only when every step after the approval can be undone in
Marvin, the same rule as an agent's approval — and the button decides as that person, at their role now."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from marvin.app import app
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import push_actions, push_notifications, web_push
from marvin.services.automation import approvals
from marvin.services.automation.authz import ROLE_EDITOR
from tests.test_workflow_approvals import _install
from tests.test_workflow_library import _entry, _entry_doc, _fire, ws  # noqa: F401 — the fixture

APPROVED = {"field": "steps.ok.output.decision", "op": "eq", "value": "approved"}
ASK = {"kind": "approval", "id": "ok", "message": "Feature “${entry.title}”?"}
UNDOABLE = {
    "trigger": {"type": "event", "event": "entry_published"},
    "actions": [ASK, {"kind": "entry", "op": "add_to_collection", "collection_slug": "featured", "when": APPROVED}],
}
PUBLISHES = {
    "trigger": {"type": "event", "event": "entry_published"},
    "actions": [ASK, {"kind": "entry", "op": "unpublish", "when": APPROVED}, {"kind": "entry", "op": "publish", "when": APPROVED}],
}


@pytest.fixture
def editor(ws):  # noqa: F811
    """The fixture's user, an EDITOR member of the workspace (the button decides at their role)."""
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    ws.session.add(WorkspaceMembers(session=ws.session, user_id=ws.uid, group_id=ws.gid, workspace_role=WorkspaceRole.EDITOR))
    ws.session.commit()
    yield ws.uid
    ws.session.query(WorkspaceMembers).filter_by(user_id=ws.uid, group_id=ws.gid).delete()
    ws.session.commit()


@pytest.fixture
def pushes(monkeypatch):
    """Push configured, every approver reachable; what is sent: [(user ids, payload dict)]."""
    sent = []
    monkeypatch.setattr(web_push, "configured", lambda: True)
    monkeypatch.setattr(web_push, "push_ready_users", lambda session, ids, category: [type("U", (), {"id": i})() for i in ids])
    monkeypatch.setattr(web_push, "workspace_member_ids", lambda session, group_id, role: [])

    def send(session, people, category, message):
        sent.append(([str(p) for p in people], json.loads(message.payload())))
        return web_push.SendResult()

    monkeypatch.setattr(web_push, "send_to_users", send)
    return sent


def _waiting(ws, definition, editor):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    ws.session.query(WorkspaceAutomationModel).filter_by(group_id=ws.gid).update({"enabled": False})  # one workflow at a time
    _install(ws, definition)
    article = _entry(ws, "article", f"Brass {uuid.uuid4().hex[:4]}", status="published", data={"body": "x"})
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id=uuid.uuid4().hex)
    (row,) = approvals.pending(ws.session, ws.gid, ROLE_EDITOR)
    return row, article


def _deliver(ws, row, editor, monkeypatch, pushes):  # noqa: F811
    monkeypatch.setattr(web_push, "workspace_member_ids", lambda session, group_id, role: [editor])
    event = type("E", (), {"event_type": type("T", (), {"name": "workflow_approval_requested"})(), "workspace_id": None, "user_id": None})()
    monkeypatch.setattr(
        push_notifications,
        "event_data",
        lambda e: {"approval_id": str(row.id), "message": row.message, "min_role": row.min_role, "automation_name": "Curate"},
    )
    push_notifications.deliver(ws.session, ws.gid, event)
    return pushes[-1][1]


def test_buttons_only_when_every_step_after_it_can_be_undone(ws, editor, monkeypatch, pushes):  # noqa: F811
    undoable, _ = _waiting(ws, UNDOABLE, editor)
    payload = _deliver(ws, undoable, editor, monkeypatch, pushes)
    assert payload["approval"]["kind"] == "workflow" and payload["approval"]["id"] == str(undoable.id) and payload["url"] == "/automation/approvals"

    approvals.decide(ws.session, ws.gid, undoable.id, "deny", user_id=editor, role=ROLE_EDITOR)
    publishes, _ = _waiting(ws, PUBLISHES, editor)
    assert "approval" not in _deliver(ws, publishes, editor, monkeypatch, pushes)  # publishing goes public: look first


def test_the_button_decides_as_that_person_once(ws, editor, monkeypatch, pushes):  # noqa: F811
    from marvin.db.models.platform.entry_collections import EntryCollections

    row, article = _waiting(ws, UNDOABLE, editor)
    token = _deliver(ws, row, editor, monkeypatch, pushes)["approval"]["token"]
    client = TestClient(app)
    url = f"/api/self/push/workflow-approvals/{row.id}/approve"

    assert client.post(f"/api/self/push/approvals/{row.id}/approve", json={"token": token}).status_code == 404  # an agent's route
    assert client.post(f"/api/self/push/workflow-approvals/{uuid.uuid4()}/approve", json={"token": token}).status_code == 404
    done = client.post(url, json={"token": token})
    assert done.status_code == 200, done.text
    assert done.json()["message"] == "Approved — the workflow went on." and done.json()["url"] == "/automation/approvals"
    ws.session.expire_all()
    assert ws.session.query(EntryCollections).filter_by(entry_id=article.id).count() == 1
    assert client.post(url, json={"token": token}).status_code == 409  # used


def test_a_workflow_changed_since_the_push_needs_a_look(ws, editor, monkeypatch, pushes):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    row, _ = _waiting(ws, UNDOABLE, editor)
    token = _deliver(ws, row, editor, monkeypatch, pushes)["approval"]["token"]
    workflow = ws.session.get(WorkspaceAutomationModel, row.automation_id)
    workflow.definition = {**UNDOABLE, "actions": [ASK, {"kind": "entry", "op": "publish", "when": APPROVED}]}
    ws.session.commit()

    refused = TestClient(app).post(f"/api/self/push/workflow-approvals/{row.id}/approve", json={"token": token})
    assert refused.status_code == 403 and "needs a look" in refused.json()["detail"]
    ws.session.refresh(row)
    assert row.status == "pending"  # still waiting, to be decided in Approvals


def test_the_restorable_rule():
    from types import SimpleNamespace

    def ok(steps):
        session = SimpleNamespace(get=lambda model, i: SimpleNamespace(definition={"actions": [ASK, *steps]}))
        return push_actions.workflow_restorable(session, SimpleNamespace(automation_id="w", step_index=0))

    assert ok([]) and ok([{"kind": "entry", "op": "create"}, {"kind": "entry", "op": "trash"}])
    assert not ok([{"kind": "entry", "op": "set_metadata"}])  # overwrites
    assert not ok([{"kind": "integration", "integration": "x", "action": "y"}])
    assert not ok([{"kind": "webhook", "webhook_id": "w"}])
