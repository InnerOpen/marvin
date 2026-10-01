"""Hand-offs (agents v2 slice D): the controller's `_delegate_runner`, the child runner a router run
hangs on its ToolContext.

The controller is built with `__new__` and every collaborator is stubbed, so this covers only the
delegate's own decisions: thread reuse vs. opening a child, stateless when there is no parent thread,
event forwarding with `via`, HTTP errors turned into error dicts, and the result shape.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.routes.ai import operations_controller as oc
from marvin.schemas.group.ai_execution import AIAgentRequest
from marvin.services.ai.agents import AgentSpec
from marvin.services.ai.operations.base import ROLE_AUTHOR

MATERIALS = AgentSpec(slug="materials", name="Materials", description="stock", default_register="playful")
CHAT_LIKE = AgentSpec(slug="talk", name="Talk", kind="model")
PRIVATE = AgentSpec(slug="private", name="Private", min_role=5)


class _Core:
    """Records every `_run_agent_core` / `_run_model_agent` call and answers with a canned result."""

    def __init__(self, result=None, raises=None):
        self.calls = []
        self.result = result or {
            "answer": "42",
            "steps": [{"tool": "search_content", "arguments": {"q": 1}, "result": "big"}],
            "referrals": [],
            "threadId": "child-1",
            "executionId": "ex-child",
            "totalTokens": 7,
        }
        self.raises = raises

    def __call__(self, *a, **kw):
        self.calls.append({"args": a, **kw})
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture
def ctl(monkeypatch):
    c = oc.AIOperationsController.__new__(oc.AIOperationsController)
    c.session = object()
    c.user = SimpleNamespace(id="u1", active_group_id="g1", group_id="g1")  # group_id is a property read off the user
    c._logger = None  # `logger` is a lazy property over _logger
    c.core = _Core()
    c.model_core = _Core({"answer": "plain", "steps": [], "threadId": None, "executionId": "ex-m", "totalTokens": 3})
    c.bound = []
    monkeypatch.setattr(c, "_run_agent_core", c.core, raising=False)
    monkeypatch.setattr(c, "_run_model_agent", c.model_core, raising=False)

    def bind(provider, agent=None, role=None, depth=0):
        c.bound.append((agent.slug, depth))
        return ["tools"], SimpleNamespace(depth=depth, referrals=[])

    monkeypatch.setattr(c, "_bind_agent_tools", bind, raising=False)
    monkeypatch.setattr(c, "_check_budget", lambda: None, raising=False)
    monkeypatch.setattr(c, "_agent_provider", lambda: SimpleNamespace(provider_type="fake"), raising=False)
    monkeypatch.setattr(c, "_default_model", lambda: "m1", raising=False)
    monkeypatch.setattr(c, "_require_tool_capable", lambda provider, model: None, raising=False)
    monkeypatch.setattr(c, "_resolve_entity_id", lambda t, i: i, raising=False)
    monkeypatch.setattr(c, "_persona", lambda: ("Marvin", "gloomy"), raising=False)
    monkeypatch.setattr(c, "_default_register", lambda: "auto", raising=False)
    monkeypatch.setattr(c, "_register_clause", lambda register, persona: f"[{register}]", raising=False)
    monkeypatch.setattr(c, "_user_role", lambda: ROLE_AUTHOR, raising=False)
    specs = {"materials": MATERIALS, "talk": CHAT_LIKE, "private": PRIVATE}
    monkeypatch.setattr(oc, "_test_specs", specs, raising=False)
    import marvin.services.ai.agents as agents_mod

    monkeypatch.setattr(agents_mod, "resolve_agent", lambda session, gid, slug: specs.get(slug))
    import marvin.services.ai.threads as threads_mod

    c.children = {}
    monkeypatch.setattr(threads_mod, "child_thread_for", lambda session, parent, slug, uid: c.children.get((str(parent.id), slug, uid)))
    return c


def _runner(ctl, parent_thread=SimpleNamespace(id="parent-1"), on_event=None, register=None):
    body = AIAgentRequest(message="route me", register=register, entityType="entry", entityId="e9", threadId="new")
    execution = SimpleNamespace(id="ex-parent")
    return ctl._delegate_runner(parent_thread=parent_thread, parent_body=body, parent_execution=execution, on_event=on_event)


def test_first_handoff_opens_a_child_thread_under_the_parent(ctl):
    out = _runner(ctl)("materials", "stock?", None)
    call = ctl.core.calls[0]
    assert call["body"].thread_id == "new" and call["body"].source == "agent" and call["body"].max_steps == oc.DELEGATED_MAX_STEPS
    assert call["parent_thread_id"] == "parent-1"
    assert call["execution_meta"] == {"parent_execution_id": "ex-parent", "parent_thread_id": "parent-1"}
    assert call["agent_slug"] == "materials" and call["operation_slug"] == "agent:materials"
    assert call["ctx"].depth == 1 and ctl.bound == [("materials", 1)]
    assert call["body"].entity_type == "entry" and call["body"].entity_id == "e9"
    assert out == {
        "agent": "materials",
        "answer": "42",
        "steps": [{"tool": "search_content", "arguments": {"q": 1}}],
        "referrals": [],
        "threadId": "child-1",
        "executionId": "ex-child",
        "totalTokens": 7,
    }


def test_a_later_handoff_continues_the_existing_child_thread(ctl):
    ctl.children[("parent-1", "materials", "u1")] = SimpleNamespace(id="child-1")
    _runner(ctl)("materials", "and now?", 20)
    body = ctl.core.calls[0]["body"]
    assert body.thread_id == "child-1"
    assert body.max_steps == oc.DELEGATED_MAX_STEPS_CAP  # the router asked for more than the cap


def test_without_a_parent_thread_the_child_is_stateless(ctl):
    _runner(ctl, parent_thread=None)("materials", "stock?", None)
    call = ctl.core.calls[0]
    assert call["body"].thread_id is None and call["parent_thread_id"] is None
    assert call["execution_meta"] == {"parent_execution_id": "ex-parent"}


def test_child_events_are_forwarded_to_the_parent_listener_tagged_via(ctl):
    seen = []

    def core(**kw):
        kw["on_event"]({"type": "tool_call", "tool": "search_content"})
        return ctl.core.result

    ctl._run_agent_core = core
    _runner(ctl, on_event=seen.append)("materials", "stock?", None)
    assert seen == [{"type": "tool_call", "tool": "search_content", "via": "materials"}]


def test_register_comes_from_the_parent_call_then_the_specialist_then_the_workspace(ctl):
    _runner(ctl, register="professional")("materials", "stock?", None)
    assert ctl.core.calls[0]["system"].endswith("[professional]")
    ctl.core.calls.clear()
    _runner(ctl)("materials", "stock?", None)
    assert ctl.core.calls[0]["system"].endswith("[playful]")
    ctl.core.calls.clear()
    # "auto" from the Ask page is not a choice: the specialist's own register wins
    _runner(ctl, register="auto")("materials", "stock?", None)
    assert ctl.core.calls[0]["system"].endswith("[playful]")
    ctl.core.calls.clear()
    _runner(ctl, register="auto")("talk", "hi", None)  # no agent default → the workspace's
    assert ctl.model_core.calls[0]["args"][3].endswith("[auto]")


def test_a_model_specialist_runs_as_a_plain_completion(ctl):
    out = _runner(ctl)("talk", "hi", None)
    assert ctl.core.calls == [] and len(ctl.model_core.calls) == 1
    call = ctl.model_core.calls[0]
    body = call["args"][4]  # (spec, provider, model, system, body)
    assert call["parent_thread_id"] == "parent-1" and body.thread_id == "new" and body.source == "agent"
    assert out["answer"] == "plain" and out["steps"] == []


@pytest.mark.parametrize(
    ("slug", "fragment"),
    [("ghost", "unknown agent"), ("private", "role level"), ("", "unknown agent")],
)
def test_unknown_or_forbidden_agents_are_error_dicts_not_exceptions(ctl, slug, fragment):
    out = _runner(ctl)(slug, "q", None)
    assert fragment in out["error"] and ctl.core.calls == []


def test_an_empty_message_is_refused_before_anything_runs(ctl):
    assert _runner(ctl)("materials", "", None) == {"error": "message is required", "agent": "materials"}


@pytest.mark.parametrize("exc", [HTTPException(429, "Daily AI budget exceeded"), HTTPException(403, "AI is disabled")])
def test_http_errors_from_the_child_run_become_error_dicts(ctl, exc):
    ctl._run_agent_core = _Core(raises=exc)
    assert _runner(ctl)("materials", "q", None) == {"error": exc.detail, "agent": "materials"}


def test_budget_check_runs_before_the_child(ctl, monkeypatch):
    monkeypatch.setattr(ctl, "_check_budget", lambda: (_ for _ in ()).throw(HTTPException(429, "budget")), raising=False)
    assert _runner(ctl)("materials", "q", None)["error"] == "budget" and ctl.core.calls == []
