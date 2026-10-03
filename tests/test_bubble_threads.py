"""Bubble runs on server threads: what a client that navigated away mid-run needs from the server.

The Marvin bubble awaits the run inside a page the user may leave. The run carries on server-side,
so the client must be able to learn the run's thread (and execution) while it is still in flight,
find the answer stored there afterwards, and have the thread — not its own replay — be the memory.

Same harness as test_agent_approval: the controller is built with `__new__` over a real
`db_session`, provider collaborators stubbed, and the loop replaced by a scripted fake.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pytest import fixture

from marvin.db.models.groups.ai_threads import AIThreadModel
from marvin.routes.ai import operations_controller as oc
from marvin.schemas.group.ai_execution import AIAgentRequest
from marvin.services.ai import agent as loop_mod
from marvin.services.ai import run_progress
from marvin.services.ai import threads as svc
from marvin.services.ai.agent import AgentResult
from marvin.services.ai.agents import AgentSpec
from marvin.services.ai.operations.base import ROLE_AUTHOR


class _Bus:
    def dispatch(self, **kw):
        pass


def _done(answer="the answer"):
    return AgentResult(answer=answer, steps=[], prompt_tokens=6, completion_tokens=4, total_tokens=10, stopped_reason="complete")


@fixture(autouse=True)
def _clean_progress():
    run_progress._reset_for_tests()
    yield
    run_progress._reset_for_tests()


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
    monkeypatch.setattr(oc.AIOperationsController, "group", property(lambda self: SimpleNamespace(name="ws")))
    monkeypatch.setattr(c, "_user_role", lambda: ROLE_AUTHOR, raising=False)
    monkeypatch.setattr(c, "_agent_context_block", lambda t, i: None, raising=False)
    monkeypatch.setattr(c, "_completion_opts", lambda: None, raising=False)
    monkeypatch.setattr(c, "_max_output_tokens", lambda: None, raising=False)
    monkeypatch.setattr(c, "_emit_budget_thresholds", lambda execution: None, raising=False)
    monkeypatch.setattr(c, "_maybe_emit_quota", lambda execution, error: None, raising=False)
    yield c
    db_session.rollback()


def _body(message="what changed?", thread_id=oc.NEW_THREAD, run_id=None, history=None):
    return AIAgentRequest(message=message, source="agent", threadId=thread_id, clientRunId=run_id, history=history or [])


def _run_core(ctl, body):
    return ctl._run_agent_core(
        provider=SimpleNamespace(provider_type="fake"),
        model="m1",
        system="sys",
        body=body,
        entity_id=None,
        tools=[],  # no run_agent: not a router, so nothing used to open the thread early
        max_steps=4,
        operation_slug="agent:marvin",
        agent_slug="marvin",
        ctx=SimpleNamespace(depth=0, referrals=[], execution_id=None, delegate=None),
    )


def _progress(ctl, run_id):
    return run_progress.get(run_id, (ctl.group_id, ctl.user.id))


def _script_loop(monkeypatch, during=None, result=None):
    """Replace the loop: call `during(messages)` while "running", then return `result`."""

    def fake(provider, model, messages, tools, options=None, max_steps=6, on_event=None, resume=None):
        if during:
            during(messages)
        return result or _done()

    monkeypatch.setattr(loop_mod, "run_agent_loop", fake)


def test_first_message_thread_and_execution_are_known_while_the_run_is_in_flight(ctl, monkeypatch):
    run_id = str(uuid.uuid4())
    seen = {}

    def during(_messages):
        live = _progress(ctl, run_id).to_dict()
        seen.update(live)
        seen["row"] = ctl.session.get(AIThreadModel, uuid.UUID(live["threadId"]))

    _script_loop(monkeypatch, during)
    res = _run_core(ctl, _body(run_id=run_id))

    assert seen["status"] == "running"
    assert seen["threadId"] == res["threadId"] and seen["executionId"] == res["executionId"]
    assert seen["row"] is not None and seen["row"].title == "what changed?"


def test_the_answer_lands_in_the_thread_even_when_nobody_reads_the_response(ctl, monkeypatch):
    run_id = str(uuid.uuid4())
    _script_loop(monkeypatch, result=_done("stored for later"))

    _run_core(ctl, _body(run_id=run_id))  # the response goes nowhere, as after a navigation

    # What a recovering client does: progress names the thread and execution; the thread holds the turn.
    live = _progress(ctl, run_id)
    assert live.status == "completed"
    thread = ctl._thread_or_404(live.thread_id)
    assert [(m.role, m.content) for m in thread.messages] == [("user", "what changed?"), ("assistant", "stored for later")]
    assert str(thread.messages[1].execution_id) == live.execution_id


def test_history_comes_from_the_thread_not_the_request(ctl, monkeypatch, db_session):
    thread = svc.create_thread(db_session, ctl.group_id, ctl.user.id, "marvin", "tags?")
    svc.append_turn(db_session, thread, "user", "which tags exist?")
    svc.append_turn(db_session, thread, "assistant", "news, events")
    sent = []
    _script_loop(monkeypatch, lambda messages: sent.extend(m.content for m in messages if m.role != "system"))

    _run_core(ctl, _body("hello?", thread_id=str(thread.id), history=[{"role": "user", "content": "a stale old topic"}]))

    assert sent == ["which tags exist?", "news, events", "hello?"]


def test_a_failed_first_run_drops_its_thread_and_progress_says_why(ctl, monkeypatch):
    run_id = str(uuid.uuid4())
    # `_fail_execution` rolls the session back, which under this flush-only harness undoes the test's rows.
    monkeypatch.setattr(ctl, "_fail_execution", lambda execution, error, start: None, raising=False)
    opened = {}

    def boom(*a, **kw):
        opened["id"] = _progress(ctl, run_id).thread_id
        raise RuntimeError("provider down")

    monkeypatch.setattr(loop_mod, "run_agent_loop", boom)
    with pytest.raises(HTTPException) as e:
        _run_core(ctl, _body(run_id=run_id))

    assert e.value.status_code == 502
    live = _progress(ctl, run_id)
    assert live.status == "failed" and "provider down" in live.error
    assert ctl.session.get(AIThreadModel, uuid.UUID(opened["id"])) is None


def test_a_model_agent_first_message_thread_is_known_mid_run(ctl):
    run_id = str(uuid.uuid4())
    seen = {}

    def complete(messages, model, opts):
        seen.update(_progress(ctl, run_id).to_dict())
        return SimpleNamespace(content="plain answer", prompt_tokens=3, completion_tokens=2, total_tokens=5)

    provider = SimpleNamespace(provider_type="fake", complete=complete)
    spec = AgentSpec(slug="poet", name="Poet", kind="model")
    res = ctl._run_model_agent(spec, provider, "m1", "sys", _body("a haiku", run_id=run_id))

    assert seen["status"] == "running" and seen["threadId"] == res["threadId"]
    assert _progress(ctl, run_id).status == "completed"
    thread = ctl._thread_or_404(res["threadId"])
    assert [m.content for m in thread.messages] == ["a haiku", "plain answer"]
