"""Direct tool calls follow the agent permission matrix.

`POST /api/ai/tools/{name}/invoke` is how MarvinMCP runs every projected registry tool. It stands in for
the workspace's main agent, `marvin`, so it resolves each call through Marvin's matrix exactly as an agent
run does (`agents.resolve_policy`), after the role floor and before the bulk-write / ask-first gate:

- Deny → refused, naming the category;
- Ask first → refused too (a direct call cannot pause for approval), pointing at the Ask page;
- Allow → runs, still behind the bulk-write and per-tool ask-first gates.

The stateless MCP `run_agent` binds only the chosen agent's Allow tools (`standalone_tools`), and the MCP
tool listing leaves out what Marvin's matrix denies.
"""

from dataclasses import replace

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from tests import test_bulk_tag_tool as bulk
from tests import test_content_role_gates as gates

workspace = gates.workspace  # fixture: a workspace with a signed-in user
ws = bulk.ws  # fixture: a workspace with assets to tag
E, AD = WorkspaceRole.EDITOR, WorkspaceRole.ADMIN


@pytest.fixture
def calls(monkeypatch):
    """Swap tool handlers for recorders: `calls.track(name)`; `calls.ran` lists the tools that ran."""
    from types import SimpleNamespace

    from marvin.services.ai.tools import TOOL_REGISTRY

    ran: list[str] = []

    def track(name: str) -> None:
        spec = TOOL_REGISTRY[name]
        monkeypatch.setitem(TOOL_REGISTRY, name, replace(spec, handler=lambda _ctx, _args, n=name: ran.append(n) or '{"ok": true}'))

    return SimpleNamespace(track=track, ran=ran)


def _marvin_policy(monkeypatch, policy: dict) -> None:
    """Give Marvin a permission matrix (built-ins have no stored override today; this stands in for one)."""
    from marvin.services.ai import agents

    monkeypatch.setitem(agents.SYSTEM_AGENTS, "marvin", replace(agents.SYSTEM_AGENTS["marvin"], tool_policy=policy))


def _invoke(workspace, role, tool: str, args: dict | None = None) -> dict:
    res = gates._sign_in(workspace, role).post(f"/api/ai/tools/{tool}/invoke", json={"args": args or {}, "source": "mcp"})
    assert res.status_code == 200, res.text
    return res.json()


# ── Ask first ────────────────────────────────────────────────────────────────


def test_ask_first_category_is_refused_and_runs_nothing(workspace, calls):
    # Marvin asks before each workflow run; an ADMIN's direct call can't be asked, so it doesn't run.
    calls.track("run_workflow")
    out = _invoke(workspace, AD, "run_workflow", {"workflow": "rebuild"})
    assert calls.ran == []
    assert "Ask first" in out["error"] and "Automation: run" in out["error"]
    assert "Ask page" in out["error"]
    assert out["category"] == "automation_run" and out["policy"] == "ask"


# ── Deny ─────────────────────────────────────────────────────────────────────


def test_denied_category_is_refused_and_runs_nothing(workspace, calls, monkeypatch):
    _marvin_policy(monkeypatch, {"links": "block"})
    calls.track("attach_tag")
    out = _invoke(workspace, E, "attach_tag", {"entity_type": "asset", "entities": ["a"], "tags": ["red"]})
    assert calls.ran == []
    assert "Links" in out["error"] and "switched off" in out["error"]
    assert "Settings → AI → Agents" in out["error"]
    assert out["category"] == "links" and out["policy"] == "block"


def test_a_tool_level_deny_beats_an_allowed_category(workspace, calls, monkeypatch):
    _marvin_policy(monkeypatch, {"links": "allow", "attach_tag": "block"})
    calls.track("attach_tag")
    calls.track("detach_tag")
    assert "error" in _invoke(workspace, E, "attach_tag", {"tags": ["red"]})
    assert "error" not in _invoke(workspace, E, "detach_tag", {"tags": ["red"]})
    assert calls.ran == ["detach_tag"]


# ── Allow ────────────────────────────────────────────────────────────────────


def test_allowed_category_runs(workspace, calls):
    calls.track("attach_tag")  # Marvin allows its in-workspace writes
    out = _invoke(workspace, E, "attach_tag", {"tags": ["red"]})
    assert out == {"ok": True} and calls.ran == ["attach_tag"]


def test_an_override_of_marvins_matrix_is_honoured(workspace, calls, monkeypatch):
    _marvin_policy(monkeypatch, {"automation_run": "allow"})
    calls.track("run_workflow")
    out = _invoke(workspace, AD, "run_workflow", {"workflow": "rebuild"})
    assert out == {"ok": True} and calls.ran == ["run_workflow"]


def test_the_role_floor_still_answers_first(workspace, calls, monkeypatch):
    _marvin_policy(monkeypatch, {"automation_run": "allow"})
    calls.track("run_workflow")
    res = gates._sign_in(workspace, E).post("/api/ai/tools/run_workflow/invoke", json={"args": {}, "source": "mcp"})
    assert res.status_code == 403 and calls.ran == []


@pytest.mark.parametrize("tool", ["list_tags", "find_entries", "list_workflows", "get_ai_settings"])
def test_read_tools_are_unaffected(workspace, tool):
    out = _invoke(workspace, AD, tool)
    assert "error" not in out, out


def test_the_bulk_gate_still_applies_after_allow(db_session, ws, monkeypatch):
    # Links explicitly Allow: a big attach is still refused and writes nothing — the matrix never lifts the bulk gate.
    _marvin_policy(monkeypatch, {"links": "allow"})
    gid, ids = ws
    out = bulk._invoke(db_session, gid, {**bulk._ALL_ASSETS, "tags": bulk._SIX_TAGS})
    assert "too large" in out["error"] and out["links"] == 24
    assert bulk._links(db_session, ids) == 0


# ── MCP tool listing ─────────────────────────────────────────────────────────


def test_tool_list_leaves_out_what_marvin_denies(workspace, monkeypatch):
    _marvin_policy(monkeypatch, {"links": "block"})
    names = {t["name"] for t in gates._sign_in(workspace, AD).get("/api/ai/tools").json()}
    assert "attach_tag" not in names and "detach_tag" not in names
    assert {"list_tags", "run_workflow"} <= names  # reads stay; Ask first stays listed (its refusal says where to run it)


# ── Stateless MCP run_agent: the chosen agent's matrix ───────────────────────


def _standalone_names(spec) -> set[str]:
    """What a stateless run of `spec` binds for an ADMIN caller (binding calls no tool, so no context is needed)."""
    from types import SimpleNamespace

    from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
    from marvin.services.ai.tools.builtins_agents import standalone_tools

    return {t.name for t in standalone_tools(spec, SimpleNamespace(), WORKSPACE_ROLE_HIERARCHY[AD])}


def test_stateless_run_agent_binds_only_marvins_allow_tools():
    from marvin.services.ai.agents import SYSTEM_AGENTS

    names = _standalone_names(SYSTEM_AGENTS["marvin"])
    assert "run_workflow" not in names  # Ask first → not bound where nothing can park
    assert {"attach_tag", "compose_entry", "list_tags"} <= names


def test_stateless_run_agent_honours_a_custom_agents_matrix():
    from marvin.services.ai.agents import AgentSpec

    writer = AgentSpec(slug="w", name="W", allow_writes=True, tool_policy={"links": "allow", "attach_tag": "block", "automation_run": "allow"})
    names = _standalone_names(writer)
    assert "detach_tag" in names and "run_workflow" in names
    assert "attach_tag" not in names  # tool-level block
    assert "compose_entry" not in names  # allow_writes defaults the rest to Ask first → not bound

    reader = AgentSpec(slug="r", name="R")
    assert not {"attach_tag", "compose_entry", "run_workflow"} & _standalone_names(reader)
    assert "list_tags" in _standalone_names(reader)
