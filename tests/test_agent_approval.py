"""Ask first (agents v2 slice C) at the controller: parking a run on its thread, resuming it with the
user's decisions, and what a new message does to a parked thread.

The controller is built with `__new__` over a real `db_session` (workspace row, threads, executions)
with every provider-facing collaborator stubbed; `run_agent_loop` is replaced by a scripted fake so
the tests drive the park/resume bookkeeping, not the loop (tests/test_agent_loop.py covers that).
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pytest import fixture

from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.routes.ai import operations_controller as oc
from marvin.schemas.group.ai_execution import AIAgentRequest
from marvin.schemas.group.ai_thread import AIThreadResumeRequest
from marvin.services.ai import agent as loop_mod
from marvin.services.ai.agent import AgentResult, AgentStep, AgentTool, PendingCall
from marvin.services.ai.agents import AgentSpec
from marvin.services.ai.base import Message, ToolCall
from marvin.services.ai.operations.base import ROLE_ADMIN, ROLE_EDITOR
from marvin.services.event_bus_service.event_types import EventTypes

WRITER = AgentSpec(slug="w", name="W", allow_writes=True)


class _Bus:
    def __init__(self):
        self.events = []

    def dispatch(self, **kw):
        self.events.append(kw)

    def types(self):
        return [e["event_type"] for e in self.events]


class _Loop:
    """Scripted `run_agent_loop`: returns the next result; records every call's kwargs."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, provider, model, messages, tools, options=None, max_steps=6, on_event=None, resume=None):
        self.calls.append({"messages": messages, "tools": tools, "max_steps": max_steps, "resume": resume, "on_event": on_event})
        res = self.results.pop(0)
        if on_event:
            for ev in getattr(res, "_events", []):
                on_event(ev)
        return res


def _awaiting(*calls, steps=(), tokens=8):
    res = AgentResult(
        answer="",
        steps=list(steps),
        prompt_tokens=tokens - 3,
        completion_tokens=3,
        total_tokens=tokens,
        stopped_reason="awaiting_approval",
        pending_calls=list(calls),
        convo=[
            Message(role="user", content="tag it"),
            Message(role="assistant", content="", tool_calls=[ToolCall(id=c.id, name=c.tool, arguments=c.arguments) for c in calls]),
        ],
    )
    res._events = [{"type": "awaiting_approval", "calls": [{"id": c.id, "tool": c.tool} for c in calls]}]
    return res


def _done(answer="tagged", steps=(), tokens=10):
    return AgentResult(
        answer=answer, steps=list(steps), prompt_tokens=tokens - 4, completion_tokens=4, total_tokens=tokens, stopped_reason="complete"
    )


def _ask_tool(name="attach_tag"):
    return AgentTool(name=name, description="", input_schema={}, run=lambda a: "{}", category="links", requires_approval=True)


@fixture
def ctl(db_session, monkeypatch):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"appr-{gid.hex[:8]}", slug=f"appr-{gid.hex[:8]}")
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
    c.bound = []
    monkeypatch.setattr(oc.AIOperationsController, "group", property(lambda self: SimpleNamespace(name="ws")))
    monkeypatch.setattr(loop_mod, "run_agent_loop", c.loop)
    monkeypatch.setattr(c, "_user_role", lambda: ROLE_ADMIN if c.user.admin else ROLE_EDITOR, raising=False)
    monkeypatch.setattr(c, "_agent_context_block", lambda t, i: None, raising=False)
    monkeypatch.setattr(c, "_bounded_history", lambda turns: [], raising=False)
    monkeypatch.setattr(c, "_completion_opts", lambda: None, raising=False)
    monkeypatch.setattr(c, "_emit_budget_thresholds", lambda execution: None, raising=False)
    monkeypatch.setattr(c, "_maybe_emit_quota", lambda execution, error: None, raising=False)
    monkeypatch.setattr(c, "_check_budget", lambda: None, raising=False)
    monkeypatch.setattr(c, "_agent_provider", lambda: SimpleNamespace(provider_type="fake"), raising=False)
    monkeypatch.setattr(c, "_default_model", lambda: "m-default", raising=False)
    monkeypatch.setattr(c, "_require_tool_capable", lambda provider, model: None, raising=False)
    monkeypatch.setattr(c, "_external_mcp_tools", lambda: [], raising=False)

    def bind(provider, agent=None, role=None, *, depth=0, park_allowed=False):
        c.bound.append({"agent": agent.slug if agent else None, "depth": depth, "park_allowed": park_allowed})
        return [_ask_tool()], SimpleNamespace(depth=depth, referrals=[], execution_id=None, delegate=None)

    c.bind_stub = bind
    yield c
    db_session.rollback()


def _run(ctl, thread_id="new", message="tag it", tools=None, max_steps=6, client_run_id=None):
    body = AIAgentRequest(message=message, source="editor", threadId=thread_id, clientRunId=client_run_id)
    return ctl._run_agent_core(
        provider=SimpleNamespace(provider_type="fake"),
        model="m1",
        system="sys",
        body=body,
        entity_id=None,
        tools=tools if tools is not None else [_ask_tool()],
        max_steps=max_steps,
        operation_slug="agent:marvin",
        agent_slug="marvin",
        ctx=SimpleNamespace(depth=0, referrals=[], execution_id=None, delegate=None),
    )


def test_run_names_its_thread_on_the_execution_before_the_loop(ctl, monkeypatch):
    # A run a restart kills never reaches the end, so the thread must be on the row from the start
    # for the next process to close it (services/ai/interrupted_runs.py).
    seen = {}

    def loop(provider, model, messages, tools, options=None, max_steps=6, on_event=None, resume=None):
        row = ctl.session.query(AIExecutionModel).filter_by(group_id=ctl.user.group_id, status="running").one()
        seen.update(row.metadata_json or {})
        return _done()

    monkeypatch.setattr(loop_mod, "run_agent_loop", loop)
    res = _run(ctl)
    assert seen["thread_id"] == res["threadId"]


def _park(ctl, calls=None, **kw):
    calls = calls or [PendingCall(id="c2", tool="attach_tag", arguments={"tag": "foo"})]
    ctl.loop.results.append(_awaiting(*calls, steps=[AgentStep(tool="search_content", arguments={"q": "x"}, result='{"results": []}')]))
    res = _run(ctl, **kw)
    thread = ctl._thread_or_404(res["threadId"])
    return res, thread


def _execution(ctl, res):
    return ctl.session.get(AIExecutionModel, uuid.UUID(res["executionId"]))


# ── Binding ──────────────────────────────────────────────────────────────────


def test_restrict_tools_keeps_ask_only_when_the_run_can_park():
    tools = [
        AgentTool(name="search_content", description="", input_schema={}, run=lambda a: "", category="entries_read"),
        AgentTool(name="compose_entry", description="", input_schema={}, run=lambda a: "", category="entries_author"),
    ]
    dropped = oc.AIOperationsController._restrict_tools(tools, WRITER, ROLE_EDITOR)
    assert [t.name for t in dropped] == ["search_content"]
    kept = oc.AIOperationsController._restrict_tools(tools, WRITER, ROLE_EDITOR, park_allowed=True)
    assert [(t.name, t.requires_approval) for t in kept] == [("search_content", False), ("compose_entry", True)]


def test_bind_parks_a_delegated_child_only_with_a_conversation_to_carry_the_ask_up_to(ctl):
    # Slice C2: a specialist under a thread-backed router parks (its ask is carried up); without one
    # (a threadless parent) "ask" stays "not bound".
    provider = SimpleNamespace(provider_type="fake")
    parent, _ = ctl._bind_agent_tools(provider, agent=WRITER, role=ROLE_EDITOR, depth=0, park_allowed=True)
    child, _ = ctl._bind_agent_tools(provider, agent=WRITER, role=ROLE_EDITOR, depth=1, park_allowed=True)
    threadless_child, _ = ctl._bind_agent_tools(provider, agent=WRITER, role=ROLE_EDITOR, depth=1, park_allowed=False)
    assert any(t.requires_approval for t in parent) and "compose_entry" in {t.name for t in parent}
    assert {t.name for t in child if t.requires_approval} == {t.name for t in parent if t.requires_approval}
    assert not any(t.requires_approval for t in threadless_child) and "compose_entry" not in {t.name for t in threadless_child}
    # depth 1 = AI_HANDOFF_MAX_DEPTH by default: the specialist cannot hand off further
    assert "run_agent" not in {t.name for t in child}


def test_bind_gates_big_bulk_writes_even_where_the_router_allows_links(ctl):
    from marvin.services.ai.agents import SYSTEM_AGENTS

    provider = SimpleNamespace(provider_type="fake")
    router = SYSTEM_AGENTS["marvin"]  # links: allow — no "ask first" from the matrix
    parked = {t.name: t for t in ctl._bind_agent_tools(provider, agent=router, role=ROLE_EDITOR, park_allowed=True)[0]}
    threadless = {t.name: t for t in ctl._bind_agent_tools(provider, agent=router, role=ROLE_EDITOR, park_allowed=False)[0]}
    child = {t.name: t for t in ctl._bind_agent_tools(provider, agent=router, role=ROLE_EDITOR, depth=1, park_allowed=False)[0]}
    assert not parked["attach_tag"].requires_approval and parked["attach_tag"].approval_check is not None
    # No thread to park on: the tool stays bound but its run() refuses a big call (no per-call check).
    assert threadless["attach_tag"].approval_check is None and child["attach_tag"].approval_check is None
    assert parked["search_content"].approval_check is None


def test_delegate_binds_the_child_without_park_allowed(ctl, monkeypatch):
    import marvin.services.ai.agents as agents_mod

    monkeypatch.setattr(agents_mod, "resolve_agent", lambda s, g, slug: WRITER)
    monkeypatch.setattr(ctl, "_bind_agent_tools", ctl.bind_stub, raising=False)
    monkeypatch.setattr(ctl, "_run_agent_core", lambda **kw: {"answer": "x", "steps": []}, raising=False)
    monkeypatch.setattr(ctl, "_persona", lambda: ("Marvin", ""), raising=False)
    monkeypatch.setattr(ctl, "_register_clause", lambda r, p: "", raising=False)
    monkeypatch.setattr(ctl, "_effective_register", lambda r, s: "auto", raising=False)
    monkeypatch.setattr(ctl, "_resolve_entity_id", lambda t, i: None, raising=False)
    run = ctl._delegate_runner(parent_thread=None, parent_body=AIAgentRequest(message="q"), parent_execution=SimpleNamespace(id="ex"), on_event=None)
    run("w", "do it", None)
    assert ctl.bound == [{"agent": "w", "depth": 1, "park_allowed": False}]


# ── Parking ──────────────────────────────────────────────────────────────────


def test_core_parks_the_run_on_its_thread(ctl):
    from marvin.services.ai import run_progress

    run_id = str(uuid.uuid4())
    res, thread = _park(ctl, client_run_id=run_id)

    assert res["stoppedReason"] == "awaiting_approval" and res["answer"] == ""
    assert res["pending"] == [{"id": "c2", "tool": "attach_tag", "arguments": {"tag": "foo"}}]
    assert [s["tool"] for s in res["steps"]] == ["search_content"] and res["sources"] == [] and res["handoffs"] == []
    assert res["totalTokens"] == 8 and res["estimatedCostUsd"] is None
    # the thread has the user's turn only, and the park
    assert [(m.role, m.content) for m in thread.messages] == [("user", "tag it")]
    assert thread.status == "awaiting_approval"
    pj = thread.pending_json
    assert pj["calls"] == res["pending"] and pj["execution_id"] == res["executionId"]
    assert pj["run"] == {"agent_slug": "marvin", "max_steps": 6, "register": None, "entity_type": None, "entity_id": None, "model": "m1"}
    assert pj["steps"][0]["tool"] == "search_content" and pj["convo"][-1]["tool_calls"][0]["id"] == "c2"
    execution = _execution(ctl, res)
    assert execution.status == "awaiting_approval" and execution.completed_at is None and execution.total_tokens == 8
    assert execution.metadata_json["thread_id"] == str(thread.id)
    assert ctl.event_bus.types() == [EventTypes.approval_requested]
    data = ctl.event_bus.events[0]["document_data"]
    assert data.agent_slug == "marvin" and data.thread_id == thread.id and data.execution_id == execution.id and data.calls == res["pending"]
    assert ctl.event_bus.events[0]["entity_type"] == "ai_thread"
    assert run_progress.get(run_id, (ctl.group_id, ctl.user.id)).status == "awaiting_approval"


# ── Resume ───────────────────────────────────────────────────────────────────


def _resume(ctl, thread, decisions, *, next_result=None, client_run_id=None):
    ctl.loop.results.append(next_result or _done(steps=[AgentStep(tool="attach_tag", arguments={"tag": "foo"}, result="{}")]))
    ctl._bind_agent_tools = ctl.bind_stub
    return ctl.resume_thread(str(thread.id), AIThreadResumeRequest(decisions=decisions, clientRunId=client_run_id))


def test_resume_runs_the_decisions_and_finishes_on_the_same_execution(ctl):
    calls = [PendingCall(id="c2", tool="attach_tag", arguments={"tag": "foo"}), PendingCall(id="c3", tool="attach_tag", arguments={"tag": "bar"})]
    parked, thread = _park(ctl, calls=calls)
    ctl.event_bus.events.clear()

    res = _resume(ctl, thread, {"c2": "approve"})  # c3 undecided → deny

    call = ctl.loop.calls[-1]
    assert call["messages"] == [] and call["max_steps"] == 6
    assert call["resume"].decisions == {"c2": "approve", "c3": "deny"}
    assert [c.id for c in call["resume"].pending] == ["c2", "c3"]
    assert [m.role for m in call["resume"].convo] == ["user", "assistant"]
    assert ctl.bound == [{"agent": "marvin", "depth": 0, "park_allowed": True}]
    assert call["tools"][0].requires_approval  # bound again with ask-first live: the run may park again

    assert res["executionId"] == parked["executionId"] and res["threadId"] == parked["threadId"]
    assert res["answer"] == "tagged" and res["stoppedReason"] == "complete"
    assert [s["tool"] for s in res["steps"]] == ["search_content", "attach_tag"]  # parked steps + new
    assert res["totalTokens"] == 18
    execution = _execution(ctl, res)
    assert execution.status == "completed" and execution.completed_at is not None
    assert (execution.prompt_tokens, execution.completion_tokens, execution.total_tokens) == (11, 7, 18)
    assert execution.output_json["answer"] == "tagged" and [s["tool"] for s in execution.output_json["steps"]] == ["search_content", "attach_tag"]
    ctl.session.refresh(thread)
    assert thread.status == "open" and thread.pending_json is None
    assert [(m.role, m.content) for m in thread.messages] == [("user", "tag it"), ("assistant", "tagged")]
    assert thread.messages[1].meta_json["totalTokens"] == 18 and thread.total_tokens == 18
    assert [s["tool"] for s in thread.messages[1].steps_json] == ["search_content", "attach_tag"]
    # a mixed batch emits both decisions, each with the full decision map
    assert ctl.event_bus.types()[:2] == [EventTypes.approval_granted, EventTypes.approval_rejected]
    assert ctl.event_bus.events[0]["document_data"].decisions == {"c2": "approve", "c3": "deny"}
    assert ctl.event_bus.events[1]["document_data"].decisions == {"c2": "approve", "c3": "deny"}
    assert ctl.event_bus.types()[2] == EventTypes.ai_operation_executed


def test_resume_deny_only_emits_rejected_only(ctl):
    _, thread = _park(ctl)
    ctl.event_bus.events.clear()
    res = _resume(ctl, thread, {"c2": "deny"}, next_result=_done(answer="skipped it"))
    assert res["answer"] == "skipped it"
    assert ctl.event_bus.types()[:1] == [EventTypes.approval_rejected] and EventTypes.approval_granted not in ctl.event_bus.types()


def test_resume_can_park_again(ctl):
    from marvin.services.ai import run_progress

    _, thread = _park(ctl)
    ctl.event_bus.events.clear()
    run_id = str(uuid.uuid4())
    again = _awaiting(
        PendingCall(id="c9", tool="attach_tag", arguments={"tag": "baz"}), steps=[AgentStep(tool="attach_tag", arguments={}, result="{}")]
    )
    res = _resume(ctl, thread, {"c2": "approve"}, next_result=again, client_run_id=run_id)
    assert res["stoppedReason"] == "awaiting_approval" and res["pending"][0]["id"] == "c9"
    assert [s["tool"] for s in res["steps"]] == ["search_content", "attach_tag"]
    ctl.session.refresh(thread)
    assert thread.status == "awaiting_approval" and thread.pending_json["calls"][0]["id"] == "c9"
    assert [s["tool"] for s in thread.pending_json["steps"]] == ["search_content", "attach_tag"]
    assert [m.role for m in thread.messages] == ["user"]  # no second user turn
    execution = _execution(ctl, res)
    assert execution.status == "awaiting_approval" and execution.total_tokens == 16
    assert ctl.event_bus.types() == [EventTypes.approval_granted, EventTypes.approval_requested]
    assert run_progress.get(run_id, (ctl.group_id, ctl.user.id)).status == "awaiting_approval"


def test_resume_409_when_nothing_is_pending_and_403_for_a_non_owner(ctl):
    _, thread = _park(ctl)
    other = ctl.user.id
    ctl.user = SimpleNamespace(id=uuid.uuid4(), admin=True, active_group_id=ctl.group_id, group_id=ctl.group_id, workspace_memberships=[])
    with pytest.raises(HTTPException) as e:
        ctl.resume_thread(str(thread.id), AIThreadResumeRequest(decisions={"c2": "approve"}))
    assert e.value.status_code == 403  # an admin sees the thread but cannot decide for its owner
    ctl.user = SimpleNamespace(id=other, admin=False, active_group_id=ctl.group_id, group_id=ctl.group_id, workspace_memberships=[])
    _resume(ctl, thread, {"c2": "approve"})
    with pytest.raises(HTTPException) as e:
        ctl.resume_thread(str(thread.id), AIThreadResumeRequest(decisions={"c2": "approve"}))
    assert e.value.status_code == 409


def test_resume_failure_leaves_the_thread_open_and_the_execution_failed(ctl, monkeypatch):
    parked, thread = _park(ctl)
    ctl._bind_agent_tools = ctl.bind_stub
    failed = []
    # `_fail_execution` rolls the session back first (a poisoned transaction must not block the failure
    # record); under this flush-only harness that would also undo the park, so record the call instead.
    monkeypatch.setattr(ctl, "_fail_execution", lambda execution, error, start: failed.append((execution.id, error)), raising=False)

    def boom(*a, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(loop_mod, "run_agent_loop", boom)
    with pytest.raises(HTTPException) as e:
        ctl.resume_thread(str(thread.id), AIThreadResumeRequest(decisions={"c2": "approve"}))
    assert e.value.status_code == 502
    ctl.session.refresh(thread)
    assert thread.status == "open" and thread.pending_json is None  # the park was cleared before the loop
    assert failed == [(uuid.UUID(parked["executionId"]), "provider down")]
    assert ctl.event_bus.types()[-1] == EventTypes.ai_operation_failed


# ── A new message on a parked thread ─────────────────────────────────────────


def test_new_message_on_a_parked_thread_denies_the_pending_calls_and_runs(ctl):
    parked, thread = _park(ctl)
    ctl.event_bus.events.clear()
    ctl.loop.results.append(_done(answer="second answer"))

    res = _run(ctl, thread_id=str(thread.id), message="never mind, list the tags")

    assert res["answer"] == "second answer" and res["executionId"] != parked["executionId"]
    ctl.session.refresh(thread)
    assert thread.status == "open" and thread.pending_json is None
    assert [(m.role, m.content) for m in thread.messages] == [
        ("user", "tag it"),
        ("assistant", oc.ABANDONED_MESSAGE),
        ("user", "never mind, list the tags"),
        ("assistant", "second answer"),
    ]
    assert thread.messages[1].meta_json == {"abandoned": True}
    old = _execution(ctl, parked)
    assert old.status == "failed" and old.error_message == oc.ABANDONED_ERROR and old.completed_at is not None
    assert ctl.event_bus.types()[0] == EventTypes.approval_rejected
    assert ctl.event_bus.events[0]["document_data"].decisions == {"c2": "deny"}


def test_new_message_on_a_parked_thread_is_refused_with_the_switch_flipped(ctl, monkeypatch):
    _, thread = _park(ctl)
    monkeypatch.setattr(oc, "PARKED_THREAD_ON_NEW_MESSAGE", "reject")
    with pytest.raises(HTTPException) as e:
        _run(ctl, thread_id=str(thread.id), message="again")
    assert e.value.status_code == 409
    ctl.session.refresh(thread)
    assert thread.status == "awaiting_approval"
