"""Slice C2: a specialist's "ask first" carried up to the conversation that handed off.

Two layers:

- the loop (`run_agent_loop`): a tool that raises `ToolDeferred` pends as a hand-off beside the batch's
  other calls; on resume its output arrives through `ResumeState.outputs`, or it stays pending and the
  loop re-parks without asking the model; flattening and path ids.
- the controller, end to end over a real `db_session` and the REAL loop with a scripted provider:
  Marvin hands off to Workshop, Workshop asks before `run_workflow`. Only provider-facing collaborators
  and the tool binding are stubbed (the bound tools are tiny closures, `run_agent` calls the real
  `_delegate_runner` through the ctx exactly as the registry tool does).
"""

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pytest import fixture

from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.db.models.groups.ai_threads import AIThreadModel
from marvin.routes.ai import operations_controller as oc
from marvin.schemas.group.ai_execution import AIAgentRequest
from marvin.schemas.group.ai_thread import AIThreadResumeRequest
from marvin.services.ai import agents as agents_mod
from marvin.services.ai import parked_runs
from marvin.services.ai.agent import (
    DECLINED_RESULT,
    NOT_PERMITTED_RESULT,
    AgentTool,
    PendingCall,
    ResumeState,
    ToolDeferred,
    flatten_pending,
    run_agent_loop,
    serialize_pending,
    split_decisions,
)
from marvin.services.ai.agents import AgentSpec
from marvin.services.ai.base import CompletionResult, Message, ToolCall
from marvin.services.ai.operations.base import ROLE_ADMIN, ROLE_AUTHOR, ROLE_EDITOR
from marvin.services.event_bus_service.event_types import EventTypes

# ── The loop ─────────────────────────────────────────────────────────────────


class _Scripted:
    """A provider that replays canned completions and records what it was sent."""

    provider_type = "fake"

    def __init__(self, *completions):
        self.completions = list(completions)
        self.calls = 0

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        self.calls += 1
        return self.completions.pop(0)


def _completion(content="", calls=()):
    return CompletionResult(content=content, prompt_tokens=1, completion_tokens=1, total_tokens=2, model="m", tool_calls=list(calls))


def _deferring_tool(child):
    def run(_args):
        raise ToolDeferred(child)

    return AgentTool(name="run_agent", description="", input_schema={}, run=run)


CHILD = {
    "agent": "workshop",
    "name": "Workshop",
    "thread_id": "t-child",
    "execution_id": "x-child",
    "calls": [{"id": "c7", "tool": "run_workflow", "arguments": {}}],
}


def test_loop_pends_a_deferred_tool_as_a_handoff_while_its_siblings_run():
    ran = []
    search = AgentTool(name="search_content", description="", input_schema={}, run=lambda a: ran.append(a) or '{"results": []}')
    provider = _Scripted(
        _completion(
            calls=[ToolCall(id="c1", name="run_agent", arguments={"agent": "workshop"}), ToolCall(id="c2", name="search_content", arguments={})]
        )
    )
    events = []

    res = run_agent_loop(provider, "m", [Message(role="user", content="q")], [_deferring_tool(CHILD), search], on_event=events.append)

    assert res.stopped_reason == "awaiting_approval" and ran == [{}]
    assert [(c.id, c.kind, c.child) for c in res.pending_calls] == [("c1", "handoff", CHILD)]
    # only the sibling answered; the deferred call stays open until its result is fed in
    assert [m.tool_call_id for m in res.convo if m.role == "tool"] == ["c2"]
    assert events[-1] == {"type": "awaiting_approval", "calls": [{"id": "c1/c7", "tool": "run_workflow", "via": "workshop"}]}
    assert {"type": "tool_result", "tool": "run_agent", "ok": True, "deferred": True} in events


def test_loop_resume_feeds_the_specialists_answer_in_as_the_tool_output():
    provider = _Scripted(_completion(content="done"))
    convo = [Message(role="user", content="q"), Message(role="assistant", content="", tool_calls=[ToolCall(id="c1", name="run_agent", arguments={})])]
    pending = [PendingCall(id="c1", tool="run_agent", arguments={}, kind="handoff", child=CHILD)]

    res = run_agent_loop(
        provider,
        "m",
        [],
        [_deferring_tool(CHILD)],
        resume=ResumeState(convo=convo, pending=pending, decisions={}, outputs={"c1": '{"answer": "42"}'}),
    )

    assert res.answer == "done" and res.stopped_reason == "complete"
    assert [(s.tool, s.result) for s in res.steps] == [("run_agent", '{"answer": "42"}')]


def test_loop_reparks_without_asking_the_model_while_a_specialist_still_waits():
    ran = []
    tag = AgentTool(name="attach_tag", description="", input_schema={}, run=lambda a: ran.append(a) or "{}", requires_approval=True)
    provider = _Scripted()  # any model call would fail: nothing to pop
    convo = [
        Message(role="user", content="q"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="run_agent", arguments={}), ToolCall(id="c2", name="attach_tag", arguments={"t": 1})],
        ),
    ]
    pending = [
        PendingCall(id="c1", tool="run_agent", arguments={}, kind="handoff", child=CHILD),
        PendingCall(id="c2", tool="attach_tag", arguments={"t": 1}),
    ]

    res = run_agent_loop(
        provider, "m", [], [_deferring_tool(CHILD), tag], resume=ResumeState(convo=convo, pending=pending, decisions={"c2": "approve"})
    )

    assert provider.calls == 0 and ran == [{"t": 1}]  # the parent's own approved call ran exactly once
    assert res.stopped_reason == "awaiting_approval" and [c.id for c in res.pending_calls] == ["c1"]
    assert [m.tool_call_id for m in res.convo if m.role == "tool"] == ["c2"]


def test_loop_an_approved_call_whose_tool_is_no_longer_bound_is_not_run():
    provider = _Scripted(_completion(content="ok"))
    convo = [
        Message(role="user", content="q"),
        Message(role="assistant", content="", tool_calls=[ToolCall(id="c1", name="run_workflow", arguments={})]),
    ]
    events = []

    res = run_agent_loop(
        provider,
        "m",
        [],
        [],
        on_event=events.append,
        resume=ResumeState(convo=convo, pending=[PendingCall(id="c1", tool="run_workflow", arguments={})], decisions={"c1": "approve"}),
    )

    assert [(s.tool, s.result) for s in res.steps] == [("run_workflow", NOT_PERMITTED_RESULT)]
    assert {"type": "declined", "tool": "run_workflow", "reason": "not_permitted"} in events


def test_flatten_pending_nests_paths_and_tags_via_at_any_depth():
    grandchild = {
        "agent": "materials",
        "name": "Materials",
        "thread_id": "t-g",
        "execution_id": "x-g",
        "calls": [{"id": "c9", "tool": "attach_tag", "arguments": {}}],
    }
    child = {
        **CHILD,
        "calls": [
            {"id": "c7", "tool": "run_workflow", "arguments": {}},
            {"id": "c8", "tool": "run_agent", "arguments": {}, "kind": "handoff", "child": grandchild},
        ],
    }
    calls = serialize_pending(
        [PendingCall(id="c0", tool="mcp__x", arguments={}), PendingCall(id="c1", tool="run_agent", arguments={}, kind="handoff", child=child)]
    )

    flat = flatten_pending(calls)

    assert [c["id"] for c in flat] == ["c0", "c1/c7", "c1/c8/c9"]
    assert "via" not in flat[0] and "kind" not in flat[0]
    assert flat[1]["via"] == "workshop" and flat[1]["viaName"] == "Workshop" and flat[1]["childThreadId"] == "t-child"
    assert flat[2]["via"] == "materials" and flat[2]["viaChain"] == ["workshop", "materials"] and flat[2]["childExecutionId"] == "x-g"
    assert split_decisions({"c0": "approve", "c1/c7": "deny", "c1/c8/c9": "approve"}, "c1") == {"c7": "deny", "c8/c9": "approve"}


# ── The controller ───────────────────────────────────────────────────────────

MARVIN = AgentSpec(slug="marvin", name="Marvin", allow_writes=True, is_system=True)
WORKSHOP = AgentSpec(slug="workshop", name="Workshop", allow_writes=True)
MATERIALS = AgentSpec(slug="materials", name="Materials", allow_writes=True)


class _Bus:
    def __init__(self):
        self.events = []

    def dispatch(self, **kw):
        self.events.append(kw)

    def of(self, event_type):
        return [e for e in self.events if e["event_type"] == event_type]


class _Provider:
    """Scripted per agent (read off the system prompt). Marvin hands each question to `handoff`
    (one or two specialists); a specialist asks before `ask_tool` `asks` times, then answers."""

    provider_type = "fake"

    def __init__(self):
        self.handoff = ["workshop"]
        self.marvin_asks = False  # Marvin also asks before an MCP send in the same batch
        self.asks = {"workshop": 1, "materials": 1}
        self.nested = {}  # specialist → the agent it hands off to (depth 2)
        self.model_calls = {}
        self._ids = 0

    def _id(self):
        self._ids += 1
        return f"call{self._ids}"

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        agent = messages[0].content.split("AGENT:", 1)[1].split()[0].lower()
        self.model_calls[agent] = self.model_calls.get(agent, 0) + 1
        last_user = max(i for i, m in enumerate(messages) if m.role == "user")
        results = [m for m in messages[last_user:] if m.role == "tool"]
        if agent == "marvin":
            if not results:
                return _completion(
                    calls=[ToolCall(id=self._id(), name="run_agent", arguments={"agent": a, "message": "please"}) for a in self.handoff]
                    + ([ToolCall(id=self._id(), name="mcp__x__send", arguments={})] if self.marvin_asks else [])
                )
            return _completion(
                content="Marvin: " + " | ".join(json.loads(r.content).get("answer") or json.loads(r.content).get("error", "") for r in results)
            )
        if agent in self.nested:
            if not results:
                return _completion(calls=[ToolCall(id=self._id(), name="run_agent", arguments={"agent": self.nested[agent], "message": "sub"})])
        elif len(results) < self.asks.get(agent, 0):
            return _completion(calls=[ToolCall(id=self._id(), name="run_workflow", arguments={"n": len(results)})])
        return _completion(content=f"{agent} answered: {results[-1].content if results else 'nothing'}")


@fixture
def ctl(db_session, monkeypatch):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"c2-{gid.hex[:8]}", slug=f"c2-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    monkeypatch.setattr(db_session, "commit", db_session.flush)

    c = oc.AIOperationsController.__new__(oc.AIOperationsController)
    c.session = db_session
    c.user = SimpleNamespace(id=uuid.uuid4(), admin=False, active_group_id=gid, group_id=gid, workspace_memberships=[])
    c._logger = None
    c.event_bus = _Bus()
    c.provider = _Provider()
    c.workflow_runs = []
    c.revoked_tools = set()
    c.max_depth = 1
    c.role = ROLE_AUTHOR
    c.specs = {"marvin": MARVIN, "workshop": WORKSHOP, "materials": MATERIALS}
    monkeypatch.setattr(oc.AIOperationsController, "group", property(lambda self: SimpleNamespace(name="ws")))
    monkeypatch.setattr(agents_mod, "resolve_agent", lambda session, gid, slug: c.specs.get((slug or "").strip().lower()))

    def bind(provider, agent=None, role=None, *, depth=0, park_allowed=False):
        ctx = SimpleNamespace(depth=depth, referrals=[], execution_id=None, delegate=None, tone_register=None)
        tools = []
        if depth < c.max_depth:
            tools.append(
                AgentTool(
                    name="run_agent",
                    description="",
                    input_schema={},
                    run=lambda a: json.dumps(ctx.delegate(a["agent"], a["message"], None)),
                    category="agents_run",
                )
            )
        if agent.slug == "marvin" and park_allowed:
            tools.append(AgentTool(name="mcp__x__send", description="", input_schema={}, run=lambda a: "{}", category="mcp", requires_approval=True))
        if agent.slug != "marvin" and park_allowed and "run_workflow" not in c.revoked_tools:
            tools.append(
                AgentTool(
                    name="run_workflow",
                    description="",
                    input_schema={},
                    run=lambda a, slug=agent.slug: c.workflow_runs.append((slug, a)) or json.dumps({"ran": slug}),
                    category="automation_run",
                    requires_approval=True,
                )
            )
        return tools, ctx

    stubs = {
        "_bind_agent_tools": bind,
        "_handoff_max_depth": lambda: c.max_depth,
        "_user_role": lambda: c.role,
        "_agent_context_block": lambda t, i: None,
        "_bounded_history": lambda turns: [],
        "_completion_opts": lambda: None,
        "_emit_budget_thresholds": lambda execution: None,
        "_maybe_emit_quota": lambda execution, error: None,
        "_check_budget": lambda: None,
        "_agent_provider": lambda: c.provider,
        "_default_model": lambda: "m-default",
        "_require_tool_capable": lambda provider, model: None,
        "_resolve_entity_id": lambda t, i: None,
        "_persona": lambda: ("Marvin", ""),
        "_register_clause": lambda *a, **k: "",
        "_effective_register": lambda *a, **k: "auto",
        "_default_register": lambda: "auto",
        "_default_agent_system_prompt": lambda name: f"AGENT:{name}",
    }
    for name, fn in stubs.items():
        monkeypatch.setattr(c, name, fn, raising=False)
    yield c
    db_session.rollback()


def _ask(ctl, message="run the nightly workflow", thread_id="new", source="ask_page", slug="marvin", client_run_id=None):
    return ctl.run_named_agent(slug, AIAgentRequest(message=message, source=source, threadId=thread_id, clientRunId=client_run_id))


def _resume(ctl, thread_id, decisions, source="ask_page", client_run_id=None):
    return ctl.resume_thread(str(thread_id), AIThreadResumeRequest(decisions=decisions, source=source, clientRunId=client_run_id))


def _thread(ctl, tid) -> AIThreadModel:
    row = ctl.session.get(AIThreadModel, uuid.UUID(str(tid)))
    ctl.session.refresh(row)
    return row


def _execution(ctl, eid) -> AIExecutionModel:
    row = ctl.session.get(AIExecutionModel, uuid.UUID(str(eid)))
    ctl.session.refresh(row)
    return row


def _child_of(ctl, root_id) -> AIThreadModel:
    return ctl.session.query(AIThreadModel).filter_by(parent_thread_id=uuid.UUID(str(root_id))).one()


# ── Parking ──────────────────────────────────────────────────────────────────


def test_a_specialists_ask_parks_both_runs_and_the_root_shows_it_with_via(ctl):
    from marvin.services.ai import run_progress

    run_id = str(uuid.uuid4())
    res = _ask(ctl, client_run_id=run_id)

    assert res["stoppedReason"] == "awaiting_approval" and res["answer"] == ""
    child = _child_of(ctl, res["threadId"])
    [pending] = res["pending"]
    assert pending["tool"] == "run_workflow" and pending["via"] == "workshop" and pending["viaName"] == "Workshop"
    hand_off_id, child_call_id = pending["id"].split("/")
    assert pending["childThreadId"] == str(child.id)
    # the specialist parked quietly on its own thread, pointing up
    assert child.status == "awaiting_approval" and child.pending_json["parent"]["thread_id"] == res["threadId"]
    assert child.pending_json["calls"][0]["id"] == child_call_id
    assert _execution(ctl, pending["childExecutionId"]).status == "awaiting_approval"
    root = _thread(ctl, res["threadId"])
    assert root.status == "awaiting_approval" and root.pending_json["calls"][0] == {
        **root.pending_json["calls"][0],
        "id": hand_off_id,
        "kind": "handoff",
    }
    assert ctl.workflow_runs == []
    # one approval_requested, on the root, naming the specialist
    [event] = ctl.event_bus.of(EventTypes.approval_requested)
    data = event["document_data"]
    assert event["entity_id"] == root.id and data.thread_id == root.id and data.via_agent == "workshop" and data.child_thread_id == child.id
    assert "via Workshop" in event["message"] and "run_workflow" in event["message"]
    # live steps: the flattened wait, once — the specialist's own wait is not forwarded
    events = run_progress.get(run_id, (ctl.group_id, ctl.user.id)).events
    waits = [e for e in events if e["type"] == "awaiting_approval"]
    assert [w["calls"] for w in waits] == [[{"id": pending["id"], "tool": "run_workflow", "via": "workshop"}]]


def test_thread_detail_flattens_the_root_and_points_a_specialist_at_its_root(ctl):
    res = _ask(ctl)
    child = _child_of(ctl, res["threadId"])
    root_detail = ctl.get_thread(res["threadId"])
    child_detail = ctl.get_thread(str(child.id))
    assert root_detail.pending == res["pending"] and root_detail.root_thread_id is None
    assert [c["id"] for c in child_detail.pending] == [res["pending"][0]["id"].split("/")[1]] and child_detail.root_thread_id == uuid.UUID(
        res["threadId"]
    )


# ── Resume ───────────────────────────────────────────────────────────────────


def test_approving_resumes_the_specialist_then_marvin_answers_once(ctl):
    res = _ask(ctl)
    path = res["pending"][0]["id"]
    child = _child_of(ctl, res["threadId"])
    ctl.event_bus.events.clear()
    marvin_calls = ctl.provider.model_calls["marvin"]

    out = _resume(ctl, res["threadId"], {path: "approve"})

    assert ctl.workflow_runs == [("workshop", {"n": 0})]
    assert out["stoppedReason"] == "complete" and out["threadId"] == res["threadId"] and out["executionId"] == res["executionId"]
    assert out["answer"].startswith("Marvin: workshop answered:") and ctl.provider.model_calls["marvin"] == marvin_calls + 1
    assert out["handoffs"] == [{"agent": "workshop", "threadId": str(child.id), "executionId": res["pending"][0]["childExecutionId"]}]
    child = _thread(ctl, child.id)
    assert child.status == "open" and [m.role for m in child.messages] == ["user", "assistant"]
    root = _thread(ctl, res["threadId"])
    assert root.status == "open" and [m.role for m in root.messages] == ["user", "assistant"]
    child_exec = _execution(ctl, res["pending"][0]["childExecutionId"])
    assert child_exec.status == "completed"
    # audit: the specialist's own call, decided by the user from the Ask page
    [entry] = child_exec.metadata_json["approvals"]
    assert entry["decided_by"] == str(ctl.user.id) and entry["surface"] == "ask_page" and entry["reason"] is None
    assert [(c["tool"], c["decision"]) for c in entry["calls"]] == [("run_workflow", "approve")]
    # events: granted once, on the root, with who/where/through whom
    [granted] = ctl.event_bus.of(EventTypes.approval_granted)
    data = granted["document_data"]
    assert data.thread_id == root.id and data.via_agent == "workshop" and data.decided_by == ctl.user.id and data.surface == "ask_page"
    assert data.decisions == {path: "approve"} and ctl.event_bus.of(EventTypes.approval_rejected) == []


def test_denying_tells_the_specialist_and_marvin_still_answers(ctl):
    res = _ask(ctl)
    out = _resume(ctl, res["threadId"], {})  # missing = deny
    assert ctl.workflow_runs == [] and out["stoppedReason"] == "complete"
    assert json.loads(DECLINED_RESULT)["error"] in out["answer"]
    [rejected] = ctl.event_bus.of(EventTypes.approval_rejected)
    assert rejected["document_data"].reason is None and rejected["document_data"].decided_by == ctl.user.id


def test_resuming_on_the_specialists_thread_forwards_to_the_root(ctl):
    res = _ask(ctl)
    child = _child_of(ctl, res["threadId"])
    local_id = child.pending_json["calls"][0]["id"]

    out = _resume(ctl, child.id, {local_id: "approve"})

    assert out["threadId"] == res["threadId"] and out["stoppedReason"] == "complete"
    assert ctl.workflow_runs == [("workshop", {"n": 0})]
    assert _thread(ctl, res["threadId"]).status == "open" and _thread(ctl, child.id).status == "open"


def test_a_specialist_that_asks_again_reparks_marvin_without_running_it(ctl):
    ctl.provider.asks["workshop"] = 2
    res = _ask(ctl)
    first = res["pending"][0]["id"]
    ctl.event_bus.events.clear()
    marvin_calls = ctl.provider.model_calls["marvin"]

    out = _resume(ctl, res["threadId"], {first: "approve"})

    assert out["stoppedReason"] == "awaiting_approval" and ctl.provider.model_calls["marvin"] == marvin_calls
    [again] = out["pending"]
    assert again["id"] != first and again["id"].split("/")[0] == first.split("/")[0] and again["via"] == "workshop"
    assert ctl.workflow_runs == [("workshop", {"n": 0})]
    assert [e["event_type"] for e in ctl.event_bus.events] == [EventTypes.approval_granted, EventTypes.approval_requested]
    assert _thread(ctl, res["threadId"]).pending_json["calls"][0]["child"]["calls"][0]["id"] == again["id"].split("/")[1]

    done = _resume(ctl, res["threadId"], {again["id"]: "approve"})
    assert done["stoppedReason"] == "complete" and len(ctl.workflow_runs) == 2
    assert len(_execution(ctl, again["childExecutionId"]).metadata_json["approvals"]) == 2  # append-only


def test_two_specialists_park_side_by_side_and_one_decision_settles_both(ctl):
    ctl.provider.handoff = ["workshop", "materials"]
    res = _ask(ctl)
    assert sorted(c["via"] for c in res["pending"]) == ["materials", "workshop"]
    out = _resume(ctl, res["threadId"], {c["id"]: "approve" for c in res["pending"]})
    assert out["stoppedReason"] == "complete" and sorted(s for s, _ in ctl.workflow_runs) == ["materials", "workshop"]


def test_the_same_specialist_twice_in_one_turn_gets_a_guard_error(ctl):
    ctl.provider.handoff = ["workshop", "workshop"]
    res = _ask(ctl)
    assert len(res["pending"]) == 1  # the second hand-off did not abandon the first
    out = _resume(ctl, res["threadId"], {res["pending"][0]["id"]: "approve"})
    assert "already waiting for the user's approval" in out["answer"]


# ── Abandon cascades ─────────────────────────────────────────────────────────


def test_a_new_message_on_marvin_abandons_the_specialist_too(ctl):
    res = _ask(ctl)
    child = _child_of(ctl, res["threadId"])
    ctl.event_bus.events.clear()
    ctl.provider.handoff = []

    _ask(ctl, message="never mind", thread_id=res["threadId"])

    child = _thread(ctl, child.id)
    assert child.status == "open" and child.messages[-1].meta_json == {"abandoned": True}
    child_exec = _execution(ctl, res["pending"][0]["childExecutionId"])
    assert child_exec.status == "failed" and child_exec.error_message == oc.ABANDONED_ERROR
    assert child_exec.metadata_json["approvals"][-1]["reason"] == "abandoned"
    [rejected] = ctl.event_bus.of(EventTypes.approval_rejected)
    assert rejected["document_data"].reason == "abandoned" and rejected["entity_id"] == uuid.UUID(res["threadId"])
    assert ctl.workflow_runs == []


def test_a_new_message_on_the_specialists_thread_abandons_marvin_too(ctl):
    res = _ask(ctl)
    child = _child_of(ctl, res["threadId"])

    _ask(ctl, message="just tell me about it instead", thread_id=str(child.id), slug="workshop")

    root = _thread(ctl, res["threadId"])
    assert root.status == "open" and root.messages[-1].meta_json == {"abandoned": True}
    assert _execution(ctl, res["executionId"]).status == "failed"
    child = _thread(ctl, child.id)
    # abandoned turn, then the new exchange (the specialist asked again and parked on its own)
    assert [m.content for m in child.messages][1] == oc.ABANDONED_MESSAGE and child.messages[2].content == "just tell me about it instead"


# ── Expiry ───────────────────────────────────────────────────────────────────


def _age(ctl, thread_id, hours):
    root = _thread(ctl, thread_id)
    root.pending_json = {**root.pending_json, "parked_at": (datetime.now(UTC) - timedelta(hours=hours)).isoformat()}
    ctl.session.flush()


def test_the_sweep_expires_an_old_park_with_its_specialist(ctl):
    res = _ask(ctl)
    child = _child_of(ctl, res["threadId"])
    _age(ctl, res["threadId"], 200)
    emitted = []

    count = parked_runs.expire_parked_runs(ctl.session, 168, lambda root, calls, execution: emitted.append((root.id, calls, execution.id)))

    assert count == 1 and emitted[0][0] == uuid.UUID(res["threadId"]) and emitted[0][1][0]["via"] == "workshop"
    for tid in (res["threadId"], child.id):
        thread = _thread(ctl, tid)
        assert thread.status == "open" and thread.messages[-1].meta_json == {"expired": True}
    for eid in (res["executionId"], res["pending"][0]["childExecutionId"]):
        assert _execution(ctl, eid).error_message == parked_runs.EXPIRED_ERROR
    assert parked_runs.expire_parked_runs(ctl.session, 168) == 0


def test_the_sweep_leaves_young_parks_and_ttl_zero_keeps_them_forever(ctl):
    res = _ask(ctl)
    assert parked_runs.expire_parked_runs(ctl.session, 168) == 0
    _age(ctl, res["threadId"], 10_000)
    assert parked_runs.expire_parked_runs(ctl.session, 0) == 0
    assert _thread(ctl, res["threadId"]).status == "awaiting_approval"


def test_resuming_an_expired_park_ends_it_with_409(ctl, monkeypatch):
    from marvin.core.config import get_app_settings

    monkeypatch.setattr(get_app_settings(), "AI_PARKED_RUN_TTL_HOURS", 24)
    res = _ask(ctl)
    _age(ctl, res["threadId"], 25)
    with pytest.raises(HTTPException) as e:
        _resume(ctl, res["threadId"], {res["pending"][0]["id"]: "approve"})
    assert e.value.status_code == 409 and ctl.workflow_runs == []
    assert _thread(ctl, res["threadId"]).status == "open"
    assert ctl.event_bus.of(EventTypes.approval_rejected)[-1]["document_data"].reason == "expired"


# ── Permissions at decision time ─────────────────────────────────────────────


def test_a_specialist_the_caller_may_no_longer_talk_to_is_not_resumed(ctl):
    res = _ask(ctl)
    ctl.specs["workshop"] = replace(WORKSHOP, min_role=ROLE_EDITOR)

    out = _resume(ctl, res["threadId"], {res["pending"][0]["id"]: "approve"})

    assert ctl.workflow_runs == [] and "no longer permitted" in out["answer"]
    child_exec = _execution(ctl, res["pending"][0]["childExecutionId"])
    assert child_exec.status == "failed" and child_exec.metadata_json["approvals"][-1]["reason"] == "no_longer_permitted"


def test_a_tool_revoked_while_waiting_is_not_run_even_when_approved(ctl):
    res = _ask(ctl)
    ctl.revoked_tools.add("run_workflow")
    out = _resume(ctl, res["threadId"], {res["pending"][0]["id"]: "approve"})
    assert ctl.workflow_runs == [] and json.loads(NOT_PERMITTED_RESULT)["error"] in out["answer"]


def test_only_the_owner_decides_even_through_a_specialists_thread(ctl):
    res = _ask(ctl)
    child = _child_of(ctl, res["threadId"])
    # an admin sees every thread but cannot decide for its owner
    ctl.user = SimpleNamespace(id=uuid.uuid4(), admin=True, active_group_id=ctl.group_id, group_id=ctl.group_id, workspace_memberships=[])
    ctl.role = ROLE_ADMIN
    for tid in (res["threadId"], child.id):
        with pytest.raises(HTTPException) as e:
            _resume(ctl, tid, {res["pending"][0]["id"]: "approve"})
        assert e.value.status_code == 403
    assert ctl.workflow_runs == []


# ── Resuming from the bubble ─────────────────────────────────────────────────


def _policy(ctl, **sources):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    row = WorkspaceAISettingsModel(session=ctl.session, group_id=ctl.group_id)
    row.invocation_sources = sources
    ctl.session.add(row)
    ctl.session.flush()


def test_bubble_resume_works_with_the_ask_page_switched_off(ctl):
    res = ctl.run_agent(AIAgentRequest(message="run it", source="bubble", threadId="new"))
    assert res["stoppedReason"] == "awaiting_approval"
    _policy(ctl, ask_page=False, bubble=True)
    out = _resume(ctl, res["threadId"], {res["pending"][0]["id"]: "approve"}, source="bubble")
    assert out["stoppedReason"] == "complete" and ctl.workflow_runs == [("workshop", {"n": 0})]
    assert ctl.event_bus.of(EventTypes.approval_granted)[-1]["document_data"].surface == "bubble"


def test_bubble_resume_is_refused_with_the_bubble_switched_off(ctl):
    res = _ask(ctl)
    _policy(ctl, bubble=False)
    with pytest.raises(HTTPException) as e:
        _resume(ctl, res["threadId"], {res["pending"][0]["id"]: "approve"}, source="bubble")
    assert e.value.status_code == 403 and ctl.workflow_runs == []
    assert _thread(ctl, res["threadId"]).status == "awaiting_approval"


# ── Hand-off depth ───────────────────────────────────────────────────────────


def test_depth_two_carries_a_grandchilds_ask_up_two_levels(ctl):
    ctl.max_depth = 2
    ctl.provider.nested = {"workshop": "materials"}
    res = _ask(ctl)
    [pending] = res["pending"]
    assert pending["via"] == "materials" and pending["viaChain"] == ["workshop", "materials"] and pending["id"].count("/") == 2

    out = _resume(ctl, res["threadId"], {pending["id"]: "approve"})

    assert out["stoppedReason"] == "complete" and ctl.workflow_runs == [("materials", {"n": 0})]
    assert "materials answered" in out["answer"]
    assert ctl.session.query(AIThreadModel).filter_by(group_id=ctl.group_id, status="awaiting_approval").count() == 0


def test_an_agent_already_in_the_chain_is_not_handed_to_again(ctl):
    ctl.max_depth = 2
    ctl.provider.nested = {"workshop": "marvin"}
    res = _ask(ctl)
    assert res["stoppedReason"] == "complete" and "already part of this hand-off" in res["answer"]


# ── Follow-ups: the run's tone reaches the authoring tools; the hourly sweep ─


def test_the_controller_hands_the_runs_tone_to_its_tools(ctl, monkeypatch):
    seen = []
    real_bind = ctl._bind_agent_tools

    def bind(*a, **kw):
        tools, ctx = real_bind(*a, **kw)
        seen.append(ctx)
        return tools, ctx

    monkeypatch.setattr(ctl, "_bind_agent_tools", bind, raising=False)
    monkeypatch.setattr(ctl, "_effective_register", lambda requested, spec: requested or "auto", raising=False)
    ctl.provider.handoff = []
    ctl.run_named_agent("marvin", AIAgentRequest(message="hi", source="ask_page", register="playful"))
    ctl.run_agent(AIAgentRequest(message="hi", source="bubble", register="professional"))
    assert [c.tone_register for c in seen] == ["playful", "professional"]


def test_the_hourly_task_expires_and_records_the_rejection(ctl, monkeypatch):
    import importlib
    from contextlib import contextmanager

    from marvin.core.config import get_app_settings

    task = importlib.import_module("marvin.services.scheduler.tasks.expire_parked_runs")

    res = _ask(ctl)
    _age(ctl, res["threadId"], 24 * 8)
    bus = _Bus()

    @contextmanager
    def session_context():
        yield ctl.session

    monkeypatch.setattr(task, "session_context", session_context)
    monkeypatch.setattr(task, "EventBusService", lambda bg_tasks=None: bus)
    monkeypatch.setattr(get_app_settings(), "AI_PARKED_RUN_TTL_HOURS", 168)

    task.expire_parked_runs()

    [event] = bus.events
    data = event["document_data"]
    assert event["event_type"] == EventTypes.approval_rejected and data.reason == "expired" and data.decided_by is None
    assert data.decisions == {res["pending"][0]["id"]: "deny"} and data.via_agent == "workshop"
    assert event["user_id"] == ctl.user.id and "expired" in event["message"]
    assert _thread(ctl, res["threadId"]).status == "open"


# ── Review follow-ups ────────────────────────────────────────────────────────


def test_a_specialist_that_fails_before_its_resume_starts_is_ended_not_left_waiting(ctl, monkeypatch):
    res = _ask(ctl)
    real = ctl._resume_leg

    def leg(thread, *a, **kw):
        if thread.agent_slug == "workshop":
            raise HTTPException(400, "No model configured. Set a default model on the provider.")
        return real(thread, *a, **kw)

    monkeypatch.setattr(ctl, "_resume_leg", leg, raising=False)
    out = _resume(ctl, res["threadId"], {res["pending"][0]["id"]: "approve"})

    assert out["stoppedReason"] == "complete" and "could not continue" in out["answer"] and ctl.workflow_runs == []
    child_exec = _execution(ctl, res["pending"][0]["childExecutionId"])
    assert child_exec.status == "failed" and child_exec.completed_at is not None
    assert child_exec.metadata_json["approvals"][-1]["reason"] == "failed"
    child = _child_of(ctl, res["threadId"])
    assert child.status == "open" and [m.role for m in child.messages] == ["user", "assistant"]


def test_a_handoff_the_router_may_no_longer_make_does_not_resume_the_specialist(ctl):
    res = _ask(ctl)
    ctl.max_depth = 0  # hand-offs switched off while the specialist waited
    out = _resume(ctl, res["threadId"], {res["pending"][0]["id"]: "approve"})
    assert ctl.workflow_runs == [] and "no longer permitted" in out["answer"]
    assert _execution(ctl, res["pending"][0]["childExecutionId"]).metadata_json["approvals"][-1]["reason"] == "no_longer_permitted"


def test_deciding_on_a_specialists_thread_is_refused_when_marvin_waits_on_more(ctl):
    ctl.provider.marvin_asks = True
    res = _ask(ctl)
    assert sorted(c.get("via", "") for c in res["pending"]) == ["", "workshop"]
    child = _child_of(ctl, res["threadId"])
    with pytest.raises(HTTPException) as e:
        _resume(ctl, child.id, {child.pending_json["calls"][0]["id"]: "approve"})
    assert e.value.status_code == 409 and res["threadId"] in e.value.detail
    assert _thread(ctl, res["threadId"]).status == "awaiting_approval" and ctl.event_bus.of(EventTypes.approval_granted) == []
    # on the root, both decide together
    out = _resume(ctl, res["threadId"], {c["id"]: "approve" for c in res["pending"]})
    assert out["stoppedReason"] == "complete" and ctl.workflow_runs == [("workshop", {"n": 0})]
