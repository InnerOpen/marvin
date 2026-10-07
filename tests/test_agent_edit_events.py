"""Editing an agent is a workspace settings change: the Event Log records who changed which agent.

Every agent edit — a custom agent's create / update / delete, a built-in's matrix PATCH, and the tool-policy
reset of either — dispatches `workspace_settings_changed` with `changed_fields` naming the agent
(`agents.<slug>`, or `agents.<slug>.<field>` for an update), a one-line message, and the user as the actor.
An edit that changes nothing records nothing. No site renders an agent, so none of this queues a site rebuild.
"""

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.agents import describe_policy_change
from tests import test_content_role_gates as gates

AD = WorkspaceRole.ADMIN
workspace = gates.workspace  # fixture: a workspace with a signed-in user


@pytest.fixture(autouse=True)
def _drop_ai_settings(workspace, db_session):
    """Remove the AI settings row a built-in override creates (SQLite doesn't cascade it with the workspace)."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    yield
    db_session.rollback()
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=workspace.gid).delete()
    db_session.commit()


def _logged(db_session, workspace):
    from marvin.db.models.platform.event_log import EventLogModel

    db_session.expire_all()
    return (
        db_session.query(EventLogModel)
        .filter(EventLogModel.workspace_id == workspace.gid, EventLogModel.event_type == "workspace_settings_changed")
        .order_by(EventLogModel.occurred_at)
        .all()
    )


def _changed_fields(row) -> list[str]:
    data = row.event_data or {}
    doc = data.get("documentData") or data.get("document_data") or {}
    return doc.get("changedFields") or doc.get("changed_fields")


def _rebuilds(db_session, workspace) -> int:
    from marvin.db.models.platform.site_rebuild_requests import SiteRebuildRequestModel

    db_session.expire_all()
    row = db_session.query(SiteRebuildRequestModel).filter_by(group_id=workspace.gid).first()
    return row.request_count if row else 0


# ── Wording ──────────────────────────────────────────────────────────────────


def test_describe_policy_change_names_categories_by_label_and_tools_by_name():
    assert describe_policy_change(None, {"automation_run": "allow"}) == ["Automation: run allow"]
    assert describe_policy_change({"automation_run": "allow", "run_workflow": "block"}, {"run_workflow": "ask"}) == [
        "Automation: run default",
        "run_workflow ask",
    ]
    assert describe_policy_change({"automation_run": "allow"}, {"automation_run": "allow"}) == []
    assert describe_policy_change(None, {}) == []


# ── Built-in agents: the matrix ───────────────────────────────────────────────


def test_a_builtin_matrix_change_is_recorded(workspace, db_session):
    client = gates._sign_in(workspace, AD)
    name = client.get("/api/ai/agents/marvin").json()["name"]

    res = client.patch("/api/ai/agents/marvin", json={"toolPolicy": {"automation_run": "allow"}})
    assert res.status_code == 200, res.text
    rows = _logged(db_session, workspace)
    assert len(rows) == 1
    assert rows[0].message_body == f"Agent permissions changed: {name} — Automation: run allow"
    assert _changed_fields(rows[0]) == ["agents.marvin.tool_policy"]
    assert str(rows[0].user_id) == str(workspace.uid)
    assert rows[0].integration_id == "ai_agents"

    # The same matrix again changes nothing, so records nothing.
    assert client.patch("/api/ai/agents/marvin", json={"toolPolicy": {"automation_run": "allow"}}).status_code == 200
    assert len(_logged(db_session, workspace)) == 1

    # The reset is recorded too.
    assert client.delete("/api/ai/agents/marvin/tool-policy").status_code == 200
    rows = _logged(db_session, workspace)
    assert len(rows) == 2
    assert rows[1].message_body.startswith(f"Agent permissions reset to default: {name} — Automation: run ")
    assert _changed_fields(rows[1]) == ["agents.marvin.tool_policy"]

    # Resetting a matrix that is already the default records nothing.
    assert client.delete("/api/ai/agents/marvin/tool-policy").status_code == 200
    assert len(_logged(db_session, workspace)) == 2


def test_a_refused_builtin_edit_records_nothing(workspace, db_session):
    client = gates._sign_in(workspace, AD)
    assert client.patch("/api/ai/agents/marvin", json={"name": "Nope"}).status_code == 400
    assert gates._sign_in(workspace, WorkspaceRole.EDITOR).patch(
        "/api/ai/agents/marvin", json={"toolPolicy": {"automation_run": "allow"}}
    ).status_code in (401, 403)
    assert _logged(db_session, workspace) == []


# ── Custom agents: create, update, reset, delete ──────────────────────────────


def test_custom_agent_edits_are_recorded(workspace, db_session):
    client = gates._sign_in(workspace, AD)

    assert client.post("/api/ai/agents", json={"slug": "writer", "name": "Writer"}).status_code == 201
    rows = _logged(db_session, workspace)
    assert [r.message_body for r in rows] == ["Agent created: Writer"]
    assert _changed_fields(rows[0]) == ["agents.writer"]
    assert str(rows[0].user_id) == str(workspace.uid)

    # Only the matrix: the permissions line.
    assert client.patch("/api/ai/agents/writer", json={"toolPolicy": {"automation_run": "allow"}}).status_code == 200
    rows = _logged(db_session, workspace)
    assert rows[-1].message_body == "Agent permissions changed: Writer — Automation: run allow"
    assert _changed_fields(rows[-1]) == ["agents.writer.tool_policy"]

    # Several fields, one of them unchanged (the description is already empty): only what changed is named.
    res = client.patch(
        "/api/ai/agents/writer",
        json={"systemPrompt": "Write well.", "description": None, "toolPolicy": {"automation_run": "allow", "links": "block"}},
    )
    assert res.status_code == 200, res.text
    rows = _logged(db_session, workspace)
    assert len(rows) == 3
    assert sorted(_changed_fields(rows[-1])) == ["agents.writer.system_prompt", "agents.writer.tool_policy"]
    assert rows[-1].message_body == "Agent changed: Writer — system prompt; permissions: Links block"

    # A PATCH that changes nothing records nothing.
    assert client.patch("/api/ai/agents/writer", json={"systemPrompt": "Write well."}).status_code == 200
    assert len(_logged(db_session, workspace)) == 3

    assert client.delete("/api/ai/agents/writer/tool-policy").status_code == 200
    rows = _logged(db_session, workspace)
    assert len(rows) == 4
    assert rows[-1].message_body.startswith("Agent permissions reset to default: Writer — ")
    assert _changed_fields(rows[-1]) == ["agents.writer.tool_policy"]

    assert client.delete("/api/ai/agents/writer").status_code == 204
    rows = _logged(db_session, workspace)
    assert rows[-1].message_body == "Agent deleted: Writer"
    assert _changed_fields(rows[-1]) == ["agents.writer"]
    assert len(rows) == 5


def test_agent_edits_queue_no_site_rebuild(workspace, db_session):
    client = gates._sign_in(workspace, AD)
    assert client.patch("/api/ai/agents/marvin", json={"toolPolicy": {"automation_run": "allow"}}).status_code == 200
    assert client.post("/api/ai/agents", json={"slug": "editor-bot", "name": "Editor bot"}).status_code == 201
    assert client.patch("/api/ai/agents/editor-bot", json={"name": "Editor"}).status_code == 200
    assert client.delete("/api/ai/agents/editor-bot").status_code == 204
    assert len(_logged(db_session, workspace)) == 4
    assert _rebuilds(db_session, workspace) == 0
