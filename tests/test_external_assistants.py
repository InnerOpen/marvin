"""Outside assistants (MCP clients) have their own permission matrix: "External assistants".

It is a policy holder, not an agent: `agents.external_agent` builds it from the main agent's effective matrix until a
workspace edits it, and only the outside-call gates (`tool_gateway.invoke_unattended`, `visible_tools`, the upload
link) and the Agents settings page read it. In-app agents keep their own matrices.
"""

import pytest

from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.group.agent import AgentCreate
from marvin.services.ai import agents
from tests import test_builtin_agent_matrix as matrix
from tests import test_content_role_gates as gates
from tests import test_invoke_follows_matrix as inv

workspace = matrix.workspace  # fixture: a workspace with a signed-in user
_drop_ai_settings = matrix._drop_ai_settings  # fixture (autouse): removes the AI settings row the overrides create
calls = inv.calls  # fixture: tool handlers swapped for recorders
E, AD = WorkspaceRole.EDITOR, WorkspaceRole.ADMIN


def _spec(db_session, workspace):
    db_session.expire_all()
    return agents.external_agent(db_session, workspace.gid)


# ── Inheritance ──────────────────────────────────────────────────────────────


def test_without_an_override_it_is_the_main_agents_effective_matrix(db_session, workspace):
    ext, main = _spec(db_session, workspace), agents.SYSTEM_AGENTS["marvin"]
    assert (ext.slug, ext.name, ext.tool_policy, ext.tool_policy_overridden) == ("external", "External assistants", main.tool_policy, False)
    assert agents.default_policy(ext, "automation_run") == "ask" and agents.default_policy(ext, "links") == "allow"  # the router's


def test_it_follows_the_main_agents_workspace_overrides_until_changed(db_session, workspace):
    matrix._set(workspace, "marvin", {"links": "block", "automation_run": "allow"})
    ext = _spec(db_session, workspace)
    assert ext.tool_policy == {"links": "block", "automation_run": "allow"} and not ext.tool_policy_overridden
    # once edited it is independent: the main agent's later changes no longer reach it
    matrix._set(workspace, "external", {"links": "allow"})
    matrix._set(workspace, "marvin", {"links": "block", "automation_run": "block"})
    ext = _spec(db_session, workspace)
    assert ext.tool_policy == {"links": "allow"} and ext.tool_policy_overridden
    assert agents.resolve_policy(ext, "run_workflow", "automation_run", 4)[0] == "ask"  # code default, not the main agent's override


def test_reset_goes_back_to_inheriting(db_session, workspace):
    matrix._set(workspace, "marvin", {"links": "block"})
    matrix._set(workspace, "external", {"links": "allow"})
    res = gates._sign_in(workspace, AD).delete("/api/ai/agents/external/tool-policy")
    assert res.status_code == 200, res.text
    assert (res.json()["toolPolicy"], res.json()["toolPolicyOverridden"]) == ({"links": "block"}, False)


# ── Outside calls use it; in-app agents do not ───────────────────────────────


def test_an_external_override_lets_an_outside_call_run_while_the_main_agent_still_asks(db_session, workspace, calls):
    from marvin.services.ai.operations.base import ROLE_ADMIN

    calls.track("run_workflow")
    refused = inv._invoke(workspace, AD, "run_workflow", {"workflow": "rebuild"})
    assert calls.ran == [] and "Ask first" in refused["error"]
    assert "Allow for External assistants (Settings → AI → Agents)" in refused["error"]
    assert "External assistants" in refused["error"] and refused["policy"] == "ask"

    matrix._set(workspace, "external", {"automation_run": "allow"})
    assert inv._invoke(workspace, AD, "run_workflow", {"workflow": "rebuild"}) == {"ok": True}
    assert calls.ran == ["run_workflow"]

    # the in-app main agent, and its in-app tool binding, are unchanged
    db_session.expire_all()
    main = agents.resolve_agent(db_session, workspace.gid, "marvin")
    assert agents.resolve_policy(main, "run_workflow", "automation_run", ROLE_ADMIN)[0] == "ask"


def test_the_main_agents_override_does_not_reach_an_edited_external(workspace, calls):
    matrix._set(workspace, "marvin", {"automation_run": "allow"})
    matrix._set(workspace, "external", {"links": "block"})
    calls.track("run_workflow")
    out = inv._invoke(workspace, AD, "run_workflow", {"workflow": "rebuild"})
    assert calls.ran == [] and "Ask first" in out["error"]


def test_tool_list_follows_the_external_matrix(workspace):
    names = lambda: {t["name"] for t in gates._sign_in(workspace, AD).get("/api/ai/tools").json()}  # noqa: E731
    assert "attach_tag" in names()
    matrix._set(workspace, "external", {"links": "block"})
    assert "attach_tag" not in names() and "run_workflow" in names()


def test_a_write_below_editor_is_still_blocked(db_session, workspace):
    matrix._set(workspace, "external", {"links": "allow"})
    ext = _spec(db_session, workspace)
    assert agents.resolve_policy(ext, "attach_tag", "links", 2) == ("block", "caller role is below EDITOR")
    out = agents.unattended_refusal(ext, "attach_tag", "links", 2)
    assert out and "External assistants writes only for an EDITOR" in out["error"]


# ── It is not an agent ───────────────────────────────────────────────────────


def test_it_appears_in_no_agent_list_or_resolver(db_session, workspace):
    listed = gates._sign_in(workspace, AD).get("/api/ai/agents").json()
    assert "external" not in {a["slug"] for a in listed}
    assert agents.resolve_agent(db_session, workspace.gid, "external") is None
    assert "external" not in {a.slug for a in agents.list_agents(db_session, workspace.gid)}
    assert "external" not in agents.SYSTEM_AGENTS and "external" not in agents.BUILTIN_POLICY_SLUGS
    c = gates._sign_in(workspace, AD)
    assert c.post("/api/ai/agents/external/run", json={"message": "hi"}).status_code in (404, 405, 422)
    assert c.post("/api/ai/agents/external/preview-prompt", json={}).status_code in (404, 405, 422)


def test_the_slug_is_reserved():
    with pytest.raises(ValueError):
        AgentCreate(slug="external", name="X")


# ── API round trip ───────────────────────────────────────────────────────────


def test_settings_round_trip(db_session, workspace):
    c = gates._sign_in(workspace, AD)
    got = c.get("/api/ai/agents/external").json()
    assert (got["name"], got["toolPolicyOverridden"]) == ("External assistants", False) and "Ask first means No" in got["description"]

    out = matrix._set(workspace, "external", {"automation_run": "allow"})
    assert out["toolPolicy"] == {"automation_run": "allow"} and out["toolPolicyOverridden"] is True
    perms = c.get("/api/ai/agents/external/permissions").json()
    assert perms["agent"] == "external" and perms["overridden"] is True
    rows = {r["id"]: r for r in perms["rows"]}
    assert (rows["automation_run"]["default"], rows["automation_run"]["inherited"]) == ("allow", "ask")
    assert matrix._patch(workspace, "external", {"name": "Bob"}).status_code == 400
    assert matrix._patch(workspace, "external", {"toolPolicy": {"links": "block"}}, role=E).status_code == 403

    db_session.expire_all()
    row = db_session.query(WorkspaceAISettingsModel).filter_by(group_id=workspace.gid).one()
    assert row.agent_tool_policies == {"external": {"automation_run": "allow"}}  # stored beside the built-ins


def test_a_stale_external_override_is_cleaned_not_trusted():
    from types import SimpleNamespace

    assert agents.clean_builtin_policies({"external": {"links": "block", "x": 1}, "chat": {"links": "block"}}) == {"external": {"links": "block"}}
    assert agents.builtin_policy_override(SimpleNamespace(agent_tool_policies={"external": {"links": "ask"}}), "external") == {"links": "ask"}
