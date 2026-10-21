"""A Playbook's `allowed-tools` narrows what the agent may call, and never widens it (ticket 07).

* the pure rule (`playbook_tool_limit`): which names count, how several Playbooks combine, what is always allowed;
* the gateway (`invoke_unattended` / `visible_tools`) given the Playbooks in effect, in the style of test_tool_gateway;
* an agent run with a scripted fake model: a narrowing Playbook blocks a call the agent could otherwise make.
"""

# ruff: noqa: F811 — imported fixtures are used as test arguments

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.tool_gateway import ALWAYS_ALLOWED, invoke_unattended, playbook_refusal, playbook_tool_limit, visible_tools
from marvin.services.playbooks import loaded_playbook_names, parse_allowed_tools, playbooks_in_effect
from tests.test_playbooks import BENCH, _ask, _playbook, _tools_called, model  # noqa: F401 — `model` is a fixture
from tests.test_tool_gateway import _echo, _user, echo_tools, workspace  # noqa: F401 — fixtures

KNOWN = {"find_entries", "list_tags", "create_draft", "trash_entries", "load_playbook", "list_playbooks", "read_playbook_file", "load_tools"}


def _pb(allowed_tools: str):
    return SimpleNamespace(allowed_tools=allowed_tools)


def _limited(db_session, gid, allowed_tools, name=BENCH):
    row = _playbook(db_session, gid, name)
    row.data_json = {**row.data_json, "allowed_tools": allowed_tools}
    db_session.commit()
    return row


# ── The rule ─────────────────────────────────────────────────────────────────


def test_tokens_split_on_spaces_and_commas_and_keep_a_qualifier_whole():
    assert parse_allowed_tools("find_entries  list_tags") == ["find_entries", "list_tags"]
    assert parse_allowed_tools("Bash(git add:*) Read, find_entries Read") == ["Bash(git add:*)", "Read", "find_entries"]
    assert parse_allowed_tools("") == [] and parse_allowed_tools(None) == []


def test_no_list_means_no_limit():
    assert playbook_tool_limit([], KNOWN) is None
    assert playbook_tool_limit([_pb("")], KNOWN) is None


def test_a_list_allows_those_tools_and_the_playbook_tools():
    limit = playbook_tool_limit([_pb("find_entries")], KNOWN)
    assert limit == {"find_entries", *ALWAYS_ALLOWED}
    assert playbook_refusal("find_entries", limit) is None
    for name in ALWAYS_ALLOWED:
        assert playbook_refusal(name, limit) is None
    refused = playbook_refusal("trash_entries", limit)
    assert refused["tool"] == "trash_entries" and "find_entries" in refused["error"]


def test_unknown_names_are_ignored():
    limit = playbook_tool_limit([_pb("find_entries made_up_tool")], KNOWN)
    assert limit == {"find_entries", *ALWAYS_ALLOWED}


def test_claude_code_names_are_ignored_and_a_list_of_only_those_does_not_narrow():
    assert playbook_tool_limit([_pb("Bash(git:*) Read Edit")], KNOWN) is None
    assert playbook_tool_limit([_pb("Bash(git:*) Read find_entries(x)")], KNOWN) == {"find_entries", *ALWAYS_ALLOWED}


def test_the_mcp_spellings_of_a_marvin_tool_match_it():
    assert playbook_tool_limit([_pb("marvin_find_entries mcp__marvin__list_tags")], KNOWN) == {"find_entries", "list_tags", *ALWAYS_ALLOWED}


def test_several_playbooks_with_lists_allow_the_union():
    limit = playbook_tool_limit([_pb("find_entries"), _pb("list_tags"), _pb("")], KNOWN)
    assert limit == {"find_entries", "list_tags", *ALWAYS_ALLOWED}


# ── The gateway ──────────────────────────────────────────────────────────────


def test_a_narrowing_playbook_limits_a_gateway_call_and_the_tool_list(workspace, db_session, echo_tools):
    user = _user(workspace, WorkspaceRole.OWNER)
    playbooks = [_pb("find_entries")]

    assert invoke_unattended(db_session, workspace.gid, user, "find_entries", {}, playbooks=playbooks)["ran"] is True
    out = invoke_unattended(db_session, workspace.gid, user, "list_tags", {}, playbooks=playbooks)
    assert out["tool"] == "list_tags" and "limits this task" in out["error"]
    assert invoke_unattended(db_session, workspace.gid, user, "list_tags", {})["ran"] is True  # nothing in effect: unchanged
    assert invoke_unattended(db_session, workspace.gid, user, "load_playbook", {"name": "x"}, playbooks=playbooks)["ran"] is True

    shown = {t.name for t in visible_tools(db_session, workspace.gid, user, playbooks=playbooks)}
    assert shown == {"find_entries", *(set(ALWAYS_ALLOWED) & {t.name for t in visible_tools(db_session, workspace.gid, user)})}


def test_a_tool_the_playbook_names_but_the_agent_may_not_use_stays_refused(workspace, db_session, echo_tools):
    viewer = _user(workspace, WorkspaceRole.VIEWER)
    playbooks = [_pb("find_entries create_draft")]  # create_draft needs more than a viewer has

    assert invoke_unattended(db_session, workspace.gid, viewer, "find_entries", {}, playbooks=playbooks)["ran"] is True
    with pytest.raises(HTTPException) as refused:
        invoke_unattended(db_session, workspace.gid, viewer, "create_draft", {}, playbooks=playbooks)
    assert refused.value.status_code == 403
    assert "create_draft" not in {t.name for t in visible_tools(db_session, workspace.gid, viewer, playbooks=playbooks)}


def test_a_list_of_unknown_names_leaves_the_gateway_as_it_was(workspace, db_session, echo_tools):
    user = _user(workspace, WorkspaceRole.OWNER)
    assert invoke_unattended(db_session, workspace.gid, user, "list_tags", {}, playbooks=[_pb("Bash(git:*) nope")])["ran"] is True


# ── In effect ────────────────────────────────────────────────────────────────


def _load_turn(name, ok=True, call_id="c1"):
    from marvin.services.ai.base import Message, ToolCall

    result = {"id": "1", "name": name} if ok else {"error": "No published Playbook", "available": []}
    return [
        Message(role="assistant", content="", tool_calls=[ToolCall(id=call_id, name="load_playbook", arguments={"name": name})]),
        Message(role="tool", content=json.dumps(result), tool_call_id=call_id),
    ]


def test_the_playbooks_in_effect_are_those_loaded_in_the_run_and_still_published(workspace, db_session):
    _limited(db_session, workspace.gid, "list_tags")
    convo = [*_load_turn(BENCH), *_load_turn("made-up", ok=False, call_id="c2")]

    assert loaded_playbook_names(convo) == [BENCH]
    assert [p.name for p in playbooks_in_effect(db_session, workspace.gid, convo)] == [BENCH]
    assert playbooks_in_effect(db_session, workspace.gid, []) == []

    from marvin.db.models.platform.entries import Entries

    db_session.query(Entries).filter_by(group_id=workspace.gid, slug=BENCH).one().status = "draft"
    db_session.commit()
    assert playbooks_in_effect(db_session, workspace.gid, convo) == []  # unpublished since: it no longer steers


# ── A run ────────────────────────────────────────────────────────────────────


def test_a_narrowing_playbook_blocks_a_call_the_agent_could_otherwise_make(workspace, db_session, model):
    _limited(db_session, workspace.gid, "list_tags")

    run = _ask(workspace, f"Please draft a {BENCH}.")

    assert _tools_called(run) == ["load_playbook", "find_entries"]  # the scripted model still tries it
    refused = json.loads(run["steps"][1]["result"])
    assert refused["tool"] == "find_entries" and "limits this task" in refused["error"]
    assert "find_entries" in model.tool_names[0] and "find_entries" not in model.tool_names[1]  # and is no longer offered
    assert {"list_tags", "load_playbook"} <= model.tool_names[1]


def test_a_playbook_that_lists_the_tool_lets_the_call_through(workspace, db_session, model):
    _limited(db_session, workspace.gid, "find_entries")

    run = _ask(workspace, f"Please draft a {BENCH}.")

    assert "error" not in json.loads(run["steps"][1]["result"])
    assert "find_entries" in model.tool_names[1]


def test_a_playbook_without_a_list_changes_nothing(workspace, db_session, model):
    _playbook(db_session, workspace.gid)

    run = _ask(workspace, f"Please draft a {BENCH}.")

    assert "error" not in json.loads(run["steps"][1]["result"])
    assert model.tool_names[0] == model.tool_names[1]
