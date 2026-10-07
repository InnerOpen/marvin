"""A workspace admin can change a built-in agent's permission matrix — and nothing else about it.

Built-in agents are code (`agents.SYSTEM_AGENTS`). A workspace's override of a persona built-in's matrix
(`marvin`, `ask`) lives on its AI settings row (`agent_tool_policies`) and `agents.resolve_agent` merges it
over the code default, so every surface that runs the agent sees the same matrix: the bubble (`POST /agent`),
the Ask page (`/agents/{slug}/run`), a delegated child, the stateless MCP `run_agent`, a direct tool call
(`/tools/{name}/invoke`, which stands in for `marvin`) and the MCP tool listing.

The matrix never lifts the floors: the allowlist, "writes need EDITOR", the bulk-write gate and a tool's own
per-call ask-first all still apply under Allow.
"""

import json
import uuid
from types import SimpleNamespace

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.group.agent import AgentUpdate
from marvin.services.ai import agents
from marvin.services.ai.operations.base import ROLE_AUTHOR
from tests import test_bubble_agent_permissions as bub
from tests import test_bulk_tag_tool as bulk
from tests import test_content_role_gates as gates
from tests import test_invoke_follows_matrix as inv

ws = bulk.ws  # fixture: a workspace with assets to tag
ctl = bub.ctl  # fixture: an AI operations controller over a fresh workspace, the loop scripted
calls = inv.calls  # fixture: tool handlers swapped for recorders
A, E, AD = WorkspaceRole.AUTHOR, WorkspaceRole.EDITOR, WorkspaceRole.ADMIN


workspace = gates.workspace  # fixture: a workspace with a signed-in user


@pytest.fixture(autouse=True)
def _drop_ai_settings(request, db_session):
    """Remove the AI settings row a test's overrides create (SQLite doesn't cascade it with the workspace)."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    w = request.getfixturevalue("workspace") if "workspace" in request.fixturenames else None
    yield
    if w is not None:
        db_session.rollback()
        db_session.query(WorkspaceAISettingsModel).filter_by(group_id=w.gid).delete()
        db_session.commit()


def _patch(workspace, slug: str, body: dict, role=AD):
    return gates._sign_in(workspace, role).patch(f"/api/ai/agents/{slug}", json=body)


def _set(workspace, slug: str, policy: dict | None) -> dict:
    res = _patch(workspace, slug, {"toolPolicy": policy})
    assert res.status_code == 200, res.text
    return res.json()


# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_only_persona_built_ins_have_an_editable_matrix():
    assert agents.BUILTIN_POLICY_SLUGS == ("marvin", "ask")


def test_stored_overrides_are_cleaned_on_read():
    settings = SimpleNamespace(agent_tool_policies={"marvin": {"links": "block", "x": "maybe", "y": 3}, "chat": {"a": "allow"}, "ghost": {"a": "allow"}})
    assert agents.builtin_policy_override(settings, "marvin") == {"links": "block"}
    assert agents.builtin_policy_override(settings, "chat") is None
    assert agents.builtin_policy_override(SimpleNamespace(agent_tool_policies="junk"), "marvin") is None
    assert agents.builtin_policy_override(None, "marvin") is None


def test_with_builtin_override_replaces_one_agent_and_drops_empties():
    row = SimpleNamespace(agent_tool_policies={"ask": {"search_docs": "block"}})
    assert agents.with_builtin_override(row, "marvin", {"links": "block"}) == {"ask": {"search_docs": "block"}, "marvin": {"links": "block"}}
    assert agents.with_builtin_override(row, "ask", None) is None
    assert agents.with_builtin_override(row, "ask", {}) is None
    assert agents.with_builtin_override(SimpleNamespace(), "marvin", {"links": "allow"}) == {"marvin": {"links": "allow"}}


def test_system_agent_merges_the_override_over_the_code_matrix(monkeypatch):
    from dataclasses import replace

    monkeypatch.setitem(agents.SYSTEM_AGENTS, "marvin", replace(agents.SYSTEM_AGENTS["marvin"], tool_policy={"links": "ask", "mcp": "block"}))
    settings = SimpleNamespace(assistant_name=None, persona_prompt=None, agent_tool_policies={"marvin": {"links": "block"}})
    spec = agents._system_agent(settings, agents.SYSTEM_AGENTS["marvin"])
    assert spec.tool_policy == {"links": "block", "mcp": "block"} and spec.tool_policy_overridden
    # nothing else about the agent changes
    code = agents.SYSTEM_AGENTS["marvin"]
    assert (spec.system_prompt, spec.model_override, spec.tool_allowlist, spec.allow_writes) == (
        code.system_prompt,
        code.model_override,
        code.tool_allowlist,
        code.allow_writes,
    )
    assert not agents._system_agent(SimpleNamespace(), agents.SYSTEM_AGENTS["ask"]).tool_policy_overridden


# ── API ──────────────────────────────────────────────────────────────────────


def test_admin_sets_marvins_matrix_and_every_read_shows_it(workspace):
    out = _set(workspace, "marvin", {"links": "block", "automation_run": "allow"})
    assert out["toolPolicy"] == {"links": "block", "automation_run": "allow"} and out["toolPolicyOverridden"] is True

    c = gates._sign_in(workspace, AD)
    assert c.get("/api/ai/agents/marvin").json()["toolPolicyOverridden"] is True
    listed = {a["slug"]: a for a in c.get("/api/ai/agents").json()}
    assert listed["marvin"]["toolPolicy"] == {"links": "block", "automation_run": "allow"}
    assert listed["ask"]["toolPolicyOverridden"] is False

    perms = c.get("/api/ai/agents/marvin/permissions").json()
    assert perms["overridden"] is True
    rows = {r["id"]: r for r in perms["rows"]}
    assert (rows["links"]["default"], rows["links"]["override"], rows["links"]["inherited"]) == ("block", "block", "allow")
    assert (rows["automation_run"]["default"], rows["automation_run"]["inherited"]) == ("allow", "ask")
    assert {t["name"]: t["decision"] for t in rows["links"]["tools"]}["attach_tag"] == "block"


def test_reset_by_delete_and_by_null_returns_to_the_code_matrix(workspace):
    _set(workspace, "marvin", {"links": "block"})
    res = gates._sign_in(workspace, AD).delete("/api/ai/agents/marvin/tool-policy")
    assert res.status_code == 200, res.text
    assert (res.json()["toolPolicy"], res.json()["toolPolicyOverridden"]) == (None, False)

    _set(workspace, "marvin", {"links": "block"})
    out = _set(workspace, "marvin", None)
    assert (out["toolPolicy"], out["toolPolicyOverridden"]) == (None, False)
    perms = gates._sign_in(workspace, AD).get("/api/ai/agents/marvin/permissions").json()
    assert perms["overridden"] is False
    assert {r["id"]: r["default"] for r in perms["rows"]}["links"] == "allow"

    # an empty matrix is the default too, not an "overridden" agent with nothing in it
    assert _set(workspace, "marvin", {})["toolPolicyOverridden"] is False


def test_overrides_are_per_agent_and_reset_separately(workspace):
    _set(workspace, "marvin", {"links": "block"})
    _set(workspace, "ask", {"search_docs": "block"})
    gates._sign_in(workspace, AD).delete("/api/ai/agents/ask/tool-policy")
    listed = {a["slug"]: a for a in gates._sign_in(workspace, AD).get("/api/ai/agents").json()}
    assert listed["marvin"]["toolPolicyOverridden"] and not listed["ask"]["toolPolicyOverridden"]


@pytest.mark.parametrize(
    "body",
    [{"name": "Bob"}, {"systemPrompt": "x"}, {"modelOverride": "m"}, {"enabled": False}, {"allowWrites": False}, {"name": "Bob", "toolPolicy": {"links": "block"}}, {}],
)
def test_only_the_matrix_of_a_built_in_is_editable(workspace, body):
    res = _patch(workspace, "marvin", body)
    assert res.status_code == 400, res.text
    assert "only its permission matrix (tool_policy) can be changed" in res.json()["detail"]
    assert gates._sign_in(workspace, AD).get("/api/ai/agents/marvin").json()["toolPolicyOverridden"] is False


def test_chat_has_no_matrix_to_change(workspace):
    res = _patch(workspace, "chat", {"toolPolicy": {"links": "block"}})
    assert res.status_code == 400 and "no permission matrix" in res.json()["detail"]
    assert gates._sign_in(workspace, AD).delete("/api/ai/agents/chat/tool-policy").status_code == 400


def test_a_built_in_still_cannot_be_deleted(workspace):
    assert gates._sign_in(workspace, AD).delete("/api/ai/agents/marvin").status_code == 400


def test_bad_policy_values_are_a_422(workspace):
    assert _patch(workspace, "marvin", {"toolPolicy": {"links": "sometimes"}}).status_code == 422


@pytest.mark.parametrize("role", [WorkspaceRole.VIEWER, A, E])
def test_below_admin_cannot_change_or_reset_a_built_in_matrix(workspace, role):
    assert _patch(workspace, "marvin", {"toolPolicy": {"links": "block"}}, role=role).status_code == 403
    assert gates._sign_in(workspace, role).delete("/api/ai/agents/marvin/tool-policy").status_code == 403


def test_owner_may_change_it(workspace):
    assert _patch(workspace, "marvin", {"toolPolicy": {"links": "block"}}, role=WorkspaceRole.OWNER).status_code == 200


def test_reset_also_clears_a_custom_agents_matrix(workspace):
    c = gates._sign_in(workspace, AD)
    assert c.post("/api/ai/agents", json={"slug": "writer", "name": "W", "toolPolicy": {"links": "allow"}}).status_code == 201
    try:
        res = c.delete("/api/ai/agents/writer/tool-policy")
        assert res.status_code == 200 and res.json()["toolPolicy"] is None
    finally:
        c.delete("/api/ai/agents/writer")


# ── Every consumer sees the merged matrix ────────────────────────────────────


def test_direct_invoke_honours_a_stored_override(workspace, calls):
    calls.track("run_workflow")
    calls.track("attach_tag")
    _set(workspace, "marvin", {"automation_run": "allow", "links": "block"})
    assert inv._invoke(workspace, AD, "run_workflow", {"workflow": "rebuild"}) == {"ok": True}
    out = inv._invoke(workspace, E, "attach_tag", {"tags": ["red"]})
    assert "switched off" in out["error"] and calls.ran == ["run_workflow"]


def test_direct_invoke_ask_first_refusal_points_at_the_new_setting(workspace, calls):
    calls.track("run_workflow")
    out = inv._invoke(workspace, AD, "run_workflow", {"workflow": "rebuild"})
    assert calls.ran == []
    assert "or set “Automation: run” to Allow for Marvin (Settings → AI → Agents)." in out["error"]


def test_mcp_tool_listing_honours_a_stored_override(workspace):
    _set(workspace, "marvin", {"links": "block"})
    names = {t["name"] for t in gates._sign_in(workspace, AD).get("/api/ai/tools").json()}
    assert "attach_tag" not in names and "list_tags" in names


def test_stateless_run_agent_binds_the_merged_matrix(db_session, workspace, monkeypatch):
    from marvin.services.ai import agent as loop_mod
    from marvin.services.ai.tools import ToolContext
    from marvin.services.ai.tools import builtins_agents as ba

    _set(workspace, "marvin", {"automation_run": "allow", "links": "block"})
    bound: list[set[str]] = []

    def loop(provider, model, messages, tools, opts=None, max_steps=6, **_):
        bound.append({t.name for t in tools})
        return bub._done()

    monkeypatch.setattr(loop_mod, "run_agent_loop", loop)
    monkeypatch.setattr(ba, "_default_model", lambda ctx: "m-default")
    user = SimpleNamespace(id=workspace.uid, admin=False, workspace_memberships=[SimpleNamespace(group_id=workspace.gid, workspace_role=AD)])
    ctx = ToolContext(session=db_session, group_id=workspace.gid, user=user, provider=SimpleNamespace(provider_type="fake"), logger=None)
    out = json.loads(ba._run_standalone(ctx, {"agent": "marvin", "message": "hi"}))
    assert out.get("answer") == "ok", out
    assert "run_workflow" in bound[-1] and "attach_tag" not in bound[-1]


def _store(ctl, slug: str, policy: dict | None) -> None:
    """Save a built-in's matrix through the controller (PATCH /agents/{slug}), as an ADMIN."""
    ctl.update_agent(slug, AgentUpdate(tool_policy=policy))


def test_bubble_and_ask_page_bind_the_stored_override(ctl):
    _store(ctl, "marvin", {bub.BLOCKED: "block", "automation_run": "allow"})
    for tools in (bub._bubble(ctl), bub._ask_page(ctl)):
        assert bub.BLOCKED not in tools
        assert tools["run_workflow"].requires_approval is False  # Allow: no longer asks first
    assert bub._surface(bub._bubble(ctl)) == bub._surface(bub._ask_page(ctl))
    listed = {t["name"]: t for t in ctl.list_agent_tools()}
    assert bub.BLOCKED not in listed and listed["run_workflow"]["asksFirst"] is False

    _store(ctl, "marvin", None)
    tools = bub._bubble(ctl)
    assert bub.BLOCKED in tools and tools["run_workflow"].requires_approval is True


def test_a_delegated_child_runs_with_its_stored_override(ctl):
    _store(ctl, "ask", {"search_docs": "block"})
    run = ctl._delegate_runner(parent_thread=None, parent_body=bub._body("ask_page", None), parent_execution=SimpleNamespace(id=uuid.uuid4()), on_event=None)
    res = run("ask", "what's in the workspace?")
    assert "error" not in res, res
    assert "search_docs" not in ctl.loop.tools[-1] and "search_content" in ctl.loop.tools[-1]


# ── Floors ───────────────────────────────────────────────────────────────────


def test_allow_never_lets_a_write_through_below_editor(ctl, monkeypatch):
    _store(ctl, "marvin", {"entries_author": "allow", "links": "allow", "automation_run": "allow", "mcp": "allow"})
    spec = agents.resolve_agent(ctl.session, ctl.group_id, "marvin")
    for tool, cat in (("compose_entry", "entries_author"), ("attach_tag", "links"), ("run_workflow", "automation_run")):
        assert agents.resolve_policy(spec, tool, cat, ROLE_AUTHOR) == (agents.POLICY_BLOCK, "caller role is below EDITOR")
    monkeypatch.setattr(ctl, "_user_role", lambda: ROLE_AUTHOR)
    tools = bub._bubble(ctl)
    assert not {"compose_entry", "attach_tag", "run_workflow", "mcp__srv__send"} & set(tools)
    assert bub.READ in tools


def test_author_direct_invoke_is_still_refused_under_allow(workspace, calls):
    calls.track("attach_tag")
    _set(workspace, "marvin", {"links": "allow"})
    res = gates._sign_in(workspace, A).post("/api/ai/tools/attach_tag/invoke", json={"args": {}, "source": "mcp"})
    assert res.status_code == 403 and calls.ran == []  # the tool's EDITOR floor answers first


def test_asks_allowlist_caps_what_allow_can_open(workspace):
    _set(workspace, "ask", {"entries_author": "allow", "compose_entry": "allow"})
    perms = gates._sign_in(workspace, AD).get("/api/ai/agents/ask/permissions").json()
    compose = next(t for r in perms["rows"] for t in r["tools"] if t["name"] == "compose_entry")
    assert (compose["decision"], compose["reason"]) == ("block", "not in the agent's allowlist")


def test_archive_entries_still_asks_per_published_call_under_allow(ctl):
    _store(ctl, "marvin", {"entries_archive": "allow", "archive_entries": "allow"})
    for tools in (bub._bubble(ctl), bub._ask_page(ctl)):
        tool = tools["archive_entries"]
        assert (tool.requires_approval, tool.approval_check is not None) == (False, True)


def test_the_bulk_gate_still_applies_under_a_stored_allow(db_session, ws):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    gid, ids = ws
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=gid, agent_tool_policies={"marvin": {"links": "allow", "attach_tag": "allow"}}))
    db_session.commit()
    try:
        assert agents.resolve_agent(db_session, gid, "marvin").tool_policy_overridden
        out = bulk._invoke(db_session, gid, {**bulk._ALL_ASSETS, "tags": bulk._SIX_TAGS})
        assert "too large" in out["error"] and bulk._links(db_session, ids) == 0
    finally:
        db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).delete()
        db_session.commit()


# ── Export / import ──────────────────────────────────────────────────────────


def test_export_import_carries_the_built_in_matrices(db_session, workspace):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.repos.all_repositories import get_repositories
    from marvin.repos.seed.workspace_exporter import WorkspaceExporter
    from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

    _set(workspace, "marvin", {"links": "block"})
    repos = get_repositories(db_session, group_id=workspace.gid)
    data = WorkspaceExporter(repos).export_workspace()
    assert data["ai_settings"]["agentToolPolicies"] == {"marvin": {"links": "block"}}

    target = uuid.uuid4()
    g = Groups(session=db_session, name=f"mx-{target.hex[:8]}", slug=f"mx-{target.hex[:8]}")
    g.id = target
    db_session.add(g)
    db_session.commit()
    try:
        data["ai_settings"]["agentToolPolicies"]["marvin"]["mcp"] = "whenever"  # not a policy: dropped
        data["ai_settings"]["agentToolPolicies"]["chat"] = {"links": "allow"}  # no matrix: dropped
        WorkspaceSeedLoader(repos)._load_data(data, overwrite=True, target_group_id=str(target))
        row = db_session.query(WorkspaceAISettingsModel).filter_by(group_id=target).one()
        assert row.agent_tool_policies == {"marvin": {"links": "block"}}
        assert agents.resolve_agent(db_session, target, "marvin").tool_policy == {"links": "block"}
    finally:
        db_session.query(WorkspaceAISettingsModel).filter_by(group_id=target).delete()
        db_session.query(Groups).filter_by(id=target).delete()
        db_session.commit()
