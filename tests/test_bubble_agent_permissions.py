"""The bubble's default Marvin (`POST /agent`) follows Marvin's permission matrix exactly as the Ask page does.

Both surfaces run the same agent, `marvin`; the bubble just reaches it through `/agent` while the Ask
page goes through `/agents/marvin/run`. These tests run both endpoints for the same caller, with the
real tool binding, and compare what the loop is handed.
"""

import uuid
from dataclasses import replace
from types import SimpleNamespace

from pytest import fixture

from marvin.routes.ai import operations_controller as oc
from marvin.schemas.group.ai_execution import AIAgentRequest
from marvin.services.ai import agent as loop_mod
from marvin.services.ai import agents as agents_mod
from marvin.services.ai.agent import AgentResult, AgentTool, PendingCall
from marvin.services.ai.base import Message, ToolCall
from marvin.services.ai.operations.base import ROLE_AUTHOR

READ = "search_content"  # entries_read: allow
ALLOWED_WRITE = "compose_entry"  # entries_author: Marvin allows (drafts are the soft gate)
ASK_FIRST = ("run_workflow", "mcp__srv__send", "mcp__srv__delete")  # automation_run / mcp / mcp_destructive
MCP_READ = "mcp__srv__read"
BLOCKED = "attach_tag"  # Marvin's built-in matrix allows links; the test blocks it explicitly


class _Bus:
    def dispatch(self, **kw):
        pass


class _Loop:
    """Scripted `run_agent_loop`: records the tools each run is handed, returns the next result."""

    def __init__(self):
        self.results: list = []
        self.tools: list[dict[str, AgentTool]] = []

    def __call__(self, provider, model, messages, tools, options=None, max_steps=6, on_event=None, resume=None):
        self.tools.append({t.name: t for t in tools})
        return self.results.pop(0) if self.results else _done()


def _done():
    return AgentResult(answer="ok", steps=[], prompt_tokens=1, completion_tokens=1, total_tokens=2, stopped_reason="complete")


def _awaiting(tool: str):
    call = PendingCall(id="c1", tool=tool, arguments={})
    return AgentResult(
        answer="",
        steps=[],
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        stopped_reason="awaiting_approval",
        pending_calls=[call],
        convo=[
            Message(role="user", content="hi"),
            Message(role="assistant", content="", tool_calls=[ToolCall(id=call.id, name=call.tool, arguments={})]),
        ],
    )


def _mcp_tools() -> list[AgentTool]:
    # Fresh objects per bind: `_restrict_tools` flags the ones it keeps as "ask first".
    def tool(name, category):
        return AgentTool(name=name, description=f"[Srv] {name}", input_schema={}, run=lambda a: "{}", category=category)

    return [tool(MCP_READ, "mcp_read"), tool("mcp__srv__send", "mcp"), tool("mcp__srv__delete", "mcp_destructive")]


@fixture
def ctl(db_session, monkeypatch):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"bub-{gid.hex[:8]}", slug=f"bub-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    monkeypatch.setattr(db_session, "commit", db_session.flush)

    c = oc.AIOperationsController.__new__(oc.AIOperationsController)
    c.session = db_session
    c.user = SimpleNamespace(id=uuid.uuid4(), admin=False, active_group_id=gid, group_id=gid, workspace_memberships=[])
    c._logger = None
    c.event_bus = _Bus()
    c.loop = _Loop()
    monkeypatch.setattr(oc.AIOperationsController, "group", property(lambda self: SimpleNamespace(name="ws")))
    monkeypatch.setattr(loop_mod, "run_agent_loop", c.loop)
    stubs = {
        "_user_role": lambda: ROLE_AUTHOR,
        "_agent_context_block": lambda t, i: None,
        "_bounded_history": lambda turns: [],
        "_completion_opts": lambda: None,
        "_emit_budget_thresholds": lambda execution: None,
        "_maybe_emit_quota": lambda execution, error: None,
        "_check_budget": lambda: None,
        "_agent_provider": lambda: SimpleNamespace(provider_type="fake"),
        "_default_model": lambda: "m-default",
        "_require_tool_capable": lambda provider, model: None,
        "_resolve_entity_id": lambda t, i: None,
        "_external_mcp_tools": _mcp_tools,
        # Prompt wording is not under test here.
        "_persona": lambda: ("Marvin", ""),
        "_register_clause": lambda *a, **k: "",
        "_default_register": lambda *a, **k: "auto",
        "_effective_register": lambda *a, **k: "auto",
    }
    for name, fn in stubs.items():
        monkeypatch.setattr(c, name, fn, raising=False)
    yield c
    db_session.rollback()


def _body(source: str, thread_id: str | None) -> AIAgentRequest:
    return AIAgentRequest(message="hi", source=source, **({"threadId": thread_id} if thread_id else {}))


def _bubble(ctl, thread_id: str | None = "new") -> dict[str, AgentTool]:
    ctl.run_agent(_body("bubble", thread_id))
    return ctl.loop.tools[-1]


def _ask_page(ctl, thread_id: str | None = "new") -> dict[str, AgentTool]:
    ctl.run_named_agent("marvin", _body("ask_page", thread_id))
    return ctl.loop.tools[-1]


def _surface(tools: dict[str, AgentTool]) -> dict[str, bool]:
    """name → requires_approval: what the run may call, and which calls pause it."""
    return {name: bool(t.requires_approval) for name, t in tools.items()}


def _block_in_marvins_matrix(monkeypatch, tool: str) -> None:
    marvin = agents_mod.SYSTEM_AGENTS["marvin"]
    monkeypatch.setitem(agents_mod.SYSTEM_AGENTS, "marvin", replace(marvin, tool_policy={tool: agents_mod.POLICY_BLOCK}))


# ── Parity with the Ask page ─────────────────────────────────────────────────


def test_bubble_marvin_binds_the_same_tools_as_the_ask_page_with_a_thread(ctl):
    assert _surface(_bubble(ctl)) == _surface(_ask_page(ctl))


def test_bubble_marvin_binds_the_same_tools_as_the_ask_page_without_a_thread(ctl):
    assert _surface(_bubble(ctl, thread_id=None)) == _surface(_ask_page(ctl, thread_id=None))


def test_bubble_marvin_drops_a_tool_marvins_matrix_blocks(ctl, monkeypatch):
    _block_in_marvins_matrix(monkeypatch, BLOCKED)
    assert BLOCKED not in _bubble(ctl) and BLOCKED not in _ask_page(ctl)


def test_bubble_marvin_flags_ask_first_tools_for_approval_when_it_has_a_thread(ctl):
    tools = _bubble(ctl)
    assert {name: tools[name].requires_approval for name in ASK_FIRST} == dict.fromkeys(ASK_FIRST, True)


def test_bubble_marvin_does_not_bind_ask_first_tools_without_a_thread(ctl):
    assert not set(ASK_FIRST) & set(_bubble(ctl, thread_id=None))


def test_bubble_marvin_keeps_reads_and_allowed_writes_unflagged(ctl):
    # Unchanged bubble behaviour: reads and Marvin's in-workspace writes run straight away.
    for thread_id in ("new", None):
        tools = _bubble(ctl, thread_id=thread_id)
        assert {name: tools[name].requires_approval for name in (READ, MCP_READ, ALLOWED_WRITE)} == {
            READ: False,
            MCP_READ: False,
            ALLOWED_WRITE: False,
        }


# ── Parking ──────────────────────────────────────────────────────────────────


def test_bubble_marvin_parks_an_ask_first_call_in_the_shape_the_bubble_handles(ctl):
    ctl.loop.results.append(_awaiting("run_workflow"))
    res = ctl.run_agent(_body("bubble", "new"))
    assert ctl.loop.tools[-1]["run_workflow"].requires_approval
    # capabilities.ts reads stoppedReason, threadId and pending[].tool to link to the Ask page.
    assert (res["stoppedReason"], res["pending"][0]["tool"], bool(res["threadId"])) == ("awaiting_approval", "run_workflow", True)
    assert ctl._thread_or_404(res["threadId"]).status == "awaiting_approval"
