"""Unit tests for the agent tool-dispatch loop (run_agent_loop).

Drives the loop with a scripted fake provider — no DB, no network. Covers: tool dispatch +
result feedback, token accounting, unknown-tool and tool-error handling, and the max-steps
force-final path.
"""

import json

from marvin.services.ai.agent import AgentTool, run_agent_loop
from marvin.services.ai.base import AIProvider, CompletionResult, Message, ToolCall


class ScriptedProvider(AIProvider):
    """Returns a pre-scripted CompletionResult per complete_with_tools call; records each call."""

    provider_type = "fake"
    display_name = "Fake"
    supports_tool_calls = True

    def __init__(self, results):
        self._results = list(results)
        self.calls = []  # list of (messages, tool_choice)

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        self.calls.append((list(messages), tool_choice))
        return self._results.pop(0)

    # unused abstract surface
    def complete(self, messages, model, options=None):  # pragma: no cover
        raise NotImplementedError

    def complete_structured(self, messages, model, output_schema, options=None):  # pragma: no cover
        raise NotImplementedError

    def list_models(self):  # pragma: no cover
        return []

    def test_connection(self):  # pragma: no cover
        return True, ""


def _result(content="", tool_calls=None, pt=5, ct=3):
    return CompletionResult(
        content=content,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=pt + ct,
        model="m",
        tool_calls=tool_calls or [],
    )


def test_agent_runs_tool_then_answers():
    provider = ScriptedProvider(
        [
            _result(tool_calls=[ToolCall(id="c1", name="echo", arguments={"x": 1})]),
            _result(content="done"),
        ]
    )
    seen = []
    tool = AgentTool(
        name="echo",
        description="echo",
        input_schema={},
        run=lambda a: seen.append(a) or json.dumps({"echo": a}),
    )

    result = run_agent_loop(provider, "m", [Message(role="user", content="hi")], [tool])

    assert result.answer == "done"
    assert result.stopped_reason == "complete"
    assert seen == [{"x": 1}]
    assert len(result.steps) == 1 and result.steps[0].tool == "echo"
    assert result.total_tokens == 16  # two model calls × 8
    # the second model call saw the assistant tool-call turn + the tool result
    second_convo = provider.calls[1][0]
    assert any(m.role == "assistant" and m.tool_calls for m in second_convo)
    assert any(m.role == "tool" and m.tool_call_id == "c1" for m in second_convo)


def test_agent_unknown_tool_is_reported_not_fatal():
    provider = ScriptedProvider(
        [
            _result(tool_calls=[ToolCall(id="c1", name="missing", arguments={})]),
            _result(content="ok"),
        ]
    )
    result = run_agent_loop(provider, "m", [Message(role="user", content="hi")], [])
    assert result.answer == "ok"
    assert "unknown tool" in result.steps[0].result


def test_agent_tool_exception_is_captured():
    def boom(_a):
        raise ValueError("nope")

    provider = ScriptedProvider(
        [
            _result(tool_calls=[ToolCall(id="c1", name="boom", arguments={})]),
            _result(content="handled"),
        ]
    )
    tool = AgentTool(name="boom", description="", input_schema={}, run=boom)
    result = run_agent_loop(provider, "m", [Message(role="user", content="hi")], [tool])
    assert "nope" in result.steps[0].result
    assert result.answer == "handled"


def test_agent_max_steps_forces_final_answer():
    always_call = _result(tool_calls=[ToolCall(id="c", name="echo", arguments={})])
    provider = ScriptedProvider([always_call, always_call, _result(content="forced final")])
    tool = AgentTool(name="echo", description="", input_schema={}, run=lambda _a: "{}")

    result = run_agent_loop(provider, "m", [Message(role="user", content="hi")], [tool], max_steps=2)

    assert result.stopped_reason == "max_steps"
    assert result.answer == "forced final"
    assert len(result.steps) == 2  # two tool dispatches within budget
    assert provider.calls[-1][1] == "none"  # final answer requested with tools disabled


def _echo_tool():
    return AgentTool(name="echo", description="echo", input_schema={"type": "object"}, run=lambda a: json.dumps(a))


def test_deferral_without_a_tool_call_is_nudged_once_then_the_tool_runs():
    provider = ScriptedProvider(
        [
            _result(content="*sigh* Give me a moment to check the brain."),
            _result(tool_calls=[ToolCall(id="c1", name="echo", arguments={"q": "today"})]),
            _result(content="Today's entry says: rest."),
        ]
    )
    res = run_agent_loop(provider, "m", [Message(role="user", content="today's brain entry?")], [_echo_tool()])
    assert res.answer == "Today's entry says: rest."
    assert [s.tool for s in res.steps] == ["echo"]
    # the second call carries the deferral and the nudge, so the model sees what it did wrong
    second_call = provider.calls[1][0]
    assert second_call[-2].role == "assistant" and "Give me a moment" in second_call[-2].content
    assert second_call[-1].role == "user" and "Do it now" in second_call[-1].content


def test_deferral_is_nudged_only_once_then_taken_as_the_answer():
    provider = ScriptedProvider([_result(content="Let me check that."), _result(content="Let me check that again.")])
    res = run_agent_loop(provider, "m", [Message(role="user", content="?")], [_echo_tool()])
    assert res.answer == "Let me check that again." and len(provider.calls) == 2


def test_deferral_with_no_tools_bound_is_returned_as_is():
    provider = ScriptedProvider([_result(content="Give me a moment.")])
    res = run_agent_loop(provider, "m", [Message(role="user", content="?")], [])
    assert res.answer == "Give me a moment." and len(provider.calls) == 1


def test_plain_answer_mentioning_a_moment_in_passing_is_not_a_deferral():
    from marvin.services.ai.agent import looks_like_deferral

    assert looks_like_deferral("I'll check the vault for that.")
    assert looks_like_deferral("*groans* Give me a second.")
    assert not looks_like_deferral("The coat took a moment of patience and three fittings.")
    assert not looks_like_deferral(None)


# ── Live events (on_event) ───────────────────────────────────────────────────


def test_loop_reports_thinking_and_tool_events_in_order():
    provider = ScriptedProvider(
        [
            _result(tool_calls=[ToolCall(id="c1", name="echo", arguments={"x": 1}), ToolCall(id="c2", name="nope", arguments={})]),
            _result(content="done"),
        ]
    )
    tool = AgentTool(name="echo", description="echo", input_schema={}, run=lambda a: json.dumps(a))
    events = []

    result = run_agent_loop(provider, "m", [Message(role="user", content="hi")], [tool], on_event=events.append)

    assert result.answer == "done"
    assert [(e["type"], e.get("tool")) for e in events] == [
        ("thinking", None),
        ("tool_call", "echo"),
        ("tool_result", "echo"),
        ("tool_call", "nope"),
        ("tool_result", "nope"),
        ("thinking", None),
    ]
    assert events[1]["arguments"] == {"x": 1}
    assert events[2]["ok"] is True
    assert events[4]["ok"] is False  # unknown tool


def test_loop_reports_a_failing_tool_as_not_ok():
    def boom(_):
        raise RuntimeError("nope")

    provider = ScriptedProvider([_result(tool_calls=[ToolCall(id="c1", name="boom", arguments={})]), _result(content="ok")])
    events = []
    run_agent_loop(
        provider,
        "m",
        [Message(role="user", content="hi")],
        [AgentTool(name="boom", description="", input_schema={}, run=boom)],
        on_event=events.append,
    )
    assert [e for e in events if e["type"] == "tool_result"] == [{"type": "tool_result", "tool": "boom", "ok": False}]


def test_a_raising_listener_never_kills_the_run():
    def bad_listener(_):
        raise RuntimeError("listener bug")

    provider = ScriptedProvider([_result(tool_calls=[ToolCall(id="c1", name="echo", arguments={})]), _result(content="fine")])
    tool = AgentTool(name="echo", description="", input_schema={}, run=lambda a: "{}")
    result = run_agent_loop(provider, "m", [Message(role="user", content="hi")], [tool], on_event=bad_listener)
    assert result.answer == "fine"
    assert len(result.steps) == 1


def test_loop_without_a_listener_is_unchanged():
    provider = ScriptedProvider([_result(content="plain")])
    result = run_agent_loop(provider, "m", [Message(role="user", content="hi")], [])
    assert result.answer == "plain"
