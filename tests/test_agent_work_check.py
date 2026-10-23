"""An agent checks its work before it finishes (services/ai/work_check.py, run_agent_loop(work_check=…)).

Off by default: without a WorkCheck the loop is unchanged (tests/test_agent_loop.py). With one, gaps Marvin sees in the
transcript (a failed tool never retried, a draft that still can't be published) and the "Done when" checklist of the
Playbooks in effect send the run back to work — at most MAX_GATE_ROUNDS times, never on the last step — and the result
records what was checked; unmet gaps are listed under the answer.
"""

import json
from types import SimpleNamespace

from marvin.services.ai.agent import AgentTool, run_agent_loop
from marvin.services.ai.base import Message, ToolCall
from marvin.services.ai.work_check import MAX_GATE_ROUNDS, WorkCheck, criteria_of, done_when, gaps_in, with_unmet
from tests.test_agent_loop import ScriptedProvider, _result

BODY = """# Writing a Bench Note

Some guidance.

## Done when
- The draft has a title and a body
- [ ] It carries at least one tag
1. It links one earlier note

## Notes
- not a criterion
"""


def _tool(name, out):
    return AgentTool(name=name, description=name, input_schema={}, run=lambda args: json.dumps(out) if not callable(out) else out(args))


def _transcript(*calls):
    """A transcript with these (tool name, JSON answer) calls."""
    convo = [Message(role="user", content="go")]
    for i, (name, out) in enumerate(calls):
        convo.append(Message(role="assistant", content="", tool_calls=[ToolCall(id=f"c{i}", name=name, arguments={})]))
        convo.append(Message(role="tool", content=json.dumps(out), tool_call_id=f"c{i}"))
    return convo


# ── parsing and Marvin's own checks ──────────────────────────────────────────────────────────────────────────────


def test_done_when_reads_the_bullets_under_its_heading_only():
    assert done_when(BODY) == ["The draft has a title and a body", "It carries at least one tag", "It links one earlier note"]
    assert done_when("## Definition of done\n* shipped") == ["shipped"]
    assert done_when("## Done-when\n- a\n") == ["a"]
    assert done_when("no checklist here") == [] and done_when(None) == []


def test_criteria_merge_playbooks_without_repeats():
    books = [
        SimpleNamespace(body=BODY),
        SimpleNamespace(body="## Done when\n- It carries at least one tag\n- Spelling checked"),
        SimpleNamespace(body=None),
    ]
    assert criteria_of(books) == ["The draft has a title and a body", "It carries at least one tag", "It links one earlier note", "Spelling checked"]


def test_gaps_are_a_failure_not_retried_and_a_draft_that_cant_be_published():
    retried = _transcript(("attach_tag", {"error": "no such tag"}), ("attach_tag", {"attached": 1}))
    assert gaps_in(retried) == []
    failed = _transcript(("attach_tag", {"error": "no such tag"}))
    assert gaps_in(failed) == ["attach_tag failed: no such tag"]
    blocked = _transcript(("create_draft", {"entryId": "e1", "title": "Juki", "warnings": ["Body is required"]}))
    assert gaps_in(blocked) == ["the draft 'Juki' can't be published yet: Body is required"]
    fixed = _transcript(
        ("create_draft", {"entryId": "e1", "title": "Juki", "warnings": ["Body is required"]}),
        ("update_draft", {"entryId": "e1", "saved": {"title": "Juki"}, "warnings": []}),
    )
    assert gaps_in(fixed) == []


def test_with_unmet_only_adds_when_something_is_left():
    assert with_unmet("Done.", {"unmet": []}) == "Done." and with_unmet("Done.", None) == "Done."
    assert with_unmet("Done.", {"unmet": ["x failed"]}) == "Done.\n\nStill to do:\n- x failed"


# ── the gate in the loop ─────────────────────────────────────────────────────────────────────────────────────────


def test_without_a_work_check_nothing_changes():
    provider = ScriptedProvider([_result(tool_calls=[ToolCall(id="c1", name="attach_tag", arguments={})]), _result(content="done")])
    res = run_agent_loop(provider, "m", [Message(role="user", content="go")], [_tool("attach_tag", {"error": "nope"})])
    assert res.answer == "done" and res.check is None and len(provider.calls) == 2


def test_a_gap_sends_the_run_back_and_it_can_fix_it():
    outs = iter([{"error": "no such tag"}, {"attached": 1}])
    tool = AgentTool(name="attach_tag", description="t", input_schema={}, run=lambda a: json.dumps(next(outs)))
    provider = ScriptedProvider(
        [
            _result(tool_calls=[ToolCall(id="c1", name="attach_tag", arguments={})]),
            _result(content="all done"),  # stops with the failure unfixed → sent back
            _result(tool_calls=[ToolCall(id="c2", name="attach_tag", arguments={})]),
            _result(content="fixed it"),
        ]
    )
    res = run_agent_loop(provider, "m", [Message(role="user", content="go")], [tool], max_steps=6, work_check=WorkCheck())
    assert res.answer == "fixed it"
    sent_back = provider.calls[2][0][-1]
    assert sent_back.role == "user" and "attach_tag failed: no such tag" in sent_back.content
    assert res.check == {"criteria": [], "unmet": [], "rounds": 1}


def test_the_checklist_is_asked_once_and_listed_in_the_check():
    items = ["The draft has a title and a body"]
    provider = ScriptedProvider([_result(content="drafted"), _result(content="Checked: ✓ title and body")])
    check = WorkCheck(criteria=lambda convo: items)
    res = run_agent_loop(provider, "m", [Message(role="user", content="go")], [_tool("noop", {})], max_steps=6, work_check=check)
    assert res.answer == "Checked: ✓ title and body" and len(provider.calls) == 2
    assert "The draft has a title and a body" in provider.calls[1][0][-1].content
    assert res.check == {"criteria": items, "unmet": [], "rounds": 1}


def test_unmet_gaps_are_listed_after_the_rounds_run_out():
    provider = ScriptedProvider(
        [_result(tool_calls=[ToolCall(id="c1", name="attach_tag", arguments={})])] + [_result(content="done")] * (MAX_GATE_ROUNDS + 1)
    )
    res = run_agent_loop(
        provider, "m", [Message(role="user", content="go")], [_tool("attach_tag", {"error": "nope"})], max_steps=8, work_check=WorkCheck()
    )
    assert res.check["rounds"] == MAX_GATE_ROUNDS and res.check["unmet"] == ["attach_tag failed: nope"]
    assert res.answer.endswith("Still to do:\n- attach_tag failed: nope")


def test_no_gate_on_the_last_step():
    provider = ScriptedProvider([_result(tool_calls=[ToolCall(id="c1", name="attach_tag", arguments={})]), _result(content="done")])
    res = run_agent_loop(
        provider, "m", [Message(role="user", content="go")], [_tool("attach_tag", {"error": "nope"})], max_steps=2, work_check=WorkCheck()
    )
    assert len(provider.calls) == 2 and res.check["rounds"] == 0 and "Still to do" in res.answer
