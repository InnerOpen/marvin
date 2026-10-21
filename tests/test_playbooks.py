# ruff: noqa: F811 — the `client` / `on` / `ws` fixtures are imported, then named as parameters
"""Playbooks 01: a published Playbook steers an agent.

Driven at two seams, like a user would meet them:

* an agent run (`POST /api/ai/agent`) with a scripted fake model that reads its own system prompt, so the catalog the
  agent is shown, the tools it calls and what the run history records are all observed from the outside;
* the tool registry as both MCP servers see it (`GET /api/ai/tools` for MarvinMCP, `tools/list` and `tools/call` at /mcp).

Playbooks are entries of the internal `playbook` type; publishing them is an Admin screen that arrives later, so the
fixtures here put entries in the states that screen will produce.
"""

import json
import re
import uuid

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.base import AIProvider, CompletionResult, ToolCall
from tests import test_content_role_gates as gates
from tests.test_remote_mcp_oauth import _connect, _mcp, _open_session, _rpc_body, client, on, ws  # noqa: F401 — fixtures

workspace = gates.workspace  # fixture: a workspace with a signed-in user

BENCH = "bench-note-voice"
BENCH_DESCRIPTION = "How to write a Mash & Burn Bench Note. Use when drafting a bench note."
BENCH_BODY = "# Bench Note voice\n\nOpen with the bench. Two short paragraphs. Sign off with the batch number."

CATALOG_HEADING = "## Playbooks"
PLAYBOOKS_KEY = "playbooks"


class FakeModel(AIProvider):
    """A scripted 'model': it reads the catalog in its system prompt, loads a Playbook whose name the request
    mentions, then looks something up with an everyday tool, then answers."""

    provider_type = "fake"
    display_name = "Fake"
    supports_tool_calls = True

    def __init__(self):
        self.systems: list[str] = []
        self.tool_names: list[set[str]] = []

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        self.systems.append(messages[0].content)
        self.tool_names.append({t["name"] if isinstance(t, dict) else t.name for t in tools})
        last = messages[-1]
        if last.role == "tool":
            called = [m for m in messages if m.role == "assistant" and m.tool_calls]
            used = [c.name for m in called for c in m.tool_calls]
            if used[-1] == "load_playbook":
                return _turn(tool_calls=[ToolCall(id="c2", name="find_entries", arguments={})])
            return _turn(content="Drafted following the Playbook.")
        asked = next(m for m in reversed(messages) if m.role == "user").content
        if forced := re.search(r"load playbook (\S+)", asked):  # a request that names one the catalog doesn't show
            return _turn(tool_calls=[ToolCall(id="c1", name="load_playbook", arguments={"name": forced.group(1)})])
        for name in re.findall(r"^- ([a-z0-9-]+):", messages[0].content, flags=re.M):
            if name in asked:
                return _turn(tool_calls=[ToolCall(id="c1", name="load_playbook", arguments={"name": name})])
        return _turn(content="Nothing special needed.")

    def complete(self, messages, model, options=None):  # pragma: no cover
        raise NotImplementedError

    def complete_structured(self, messages, model, output_schema, options=None):  # pragma: no cover
        raise NotImplementedError

    def list_models(self):  # pragma: no cover
        return []

    def test_connection(self):  # pragma: no cover
        return True, ""


def _turn(content="", tool_calls=None):
    return CompletionResult(content=content, prompt_tokens=5, completion_tokens=3, total_tokens=8, model="m", tool_calls=tool_calls or [])


def _playbook(db_session, gid, name=BENCH, *, description=BENCH_DESCRIPTION, body=BENCH_BODY, status="published"):
    from marvin.db.models.platform.entries import Entries
    from marvin.services.playbooks import ensure_playbook_type

    row = Entries(
        session=db_session,
        group_id=gid,
        entry_type_id=ensure_playbook_type(db_session, gid),
        title=name,
        slug=name,
        status=status,
        data_json={"name": name, "description": description, "body": body},
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def model(monkeypatch):
    """The workspace's AI provider, swapped for the scripted model."""
    from marvin.routes.ai.operations_controller import AIOperationsController

    fake = FakeModel()
    monkeypatch.setattr(AIOperationsController, "_agent_provider", lambda self: fake)
    monkeypatch.setattr(AIOperationsController, "_default_model", lambda self: "m")
    return fake


def _ask(workspace, message, role=WorkspaceRole.AUTHOR) -> dict:
    res = gates._sign_in(workspace, role).post("/api/ai/agent", json={"message": message, "source": "api"})
    assert res.status_code == 200, res.text
    return res.json()


def _tools_called(run) -> list[str]:
    return [s["tool"] for s in run["steps"]]


def _execution(db_session, run):
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    db_session.expire_all()
    return db_session.query(AIExecutionModel).filter_by(id=run["executionId"]).one()


# ── The run ──────────────────────────────────────────────────────────────────


def test_a_matching_request_loads_the_playbook_then_uses_an_existing_tool(workspace, db_session, model):
    _playbook(db_session, workspace.gid)

    run = _ask(workspace, f"Please draft a {BENCH} for the hand-dyed batch.")

    assert _tools_called(run) == ["load_playbook", "find_entries"]
    loaded = json.loads(run["steps"][0]["result"])
    assert loaded["name"] == BENCH and loaded["body"] == BENCH_BODY
    assert run["answer"] == "Drafted following the Playbook."


def test_a_request_that_matches_nothing_loads_nothing(workspace, db_session, model):
    _playbook(db_session, workspace.gid)

    run = _ask(workspace, "What day is it?")

    assert _tools_called(run) == []
    assert run["answer"] == "Nothing special needed."
    assert PLAYBOOKS_KEY not in (_execution(db_session, run).metadata_json or {})


def test_the_run_history_records_the_playbooks_loaded(workspace, db_session, model):
    row = _playbook(db_session, workspace.gid)

    run = _ask(workspace, f"Please draft a {BENCH}.")

    meta = _execution(db_session, run).metadata_json
    assert meta[PLAYBOOKS_KEY] == [{"id": str(row.id), "name": BENCH}]
    assert meta["tools"] == ["load_playbook", "find_entries"]  # the Playbook is also an ordinary tool use


# ── The catalog in the system frame ──────────────────────────────────────────


def test_the_system_frame_carries_the_catalog_of_published_playbooks(workspace, db_session, model):
    _playbook(db_session, workspace.gid)
    _playbook(db_session, workspace.gid, "returns-policy", description="How to answer a returns question.")

    _ask(workspace, "hello")

    system = model.systems[0]
    assert CATALOG_HEADING in system
    assert f"- {BENCH}: {BENCH_DESCRIPTION}" in system
    assert "- returns-policy: How to answer a returns question." in system
    assert "load_playbook" in system
    assert BENCH_BODY not in system  # only the one-line catalog; the text loads on demand
    assert {"list_playbooks", "load_playbook"} <= model.tool_names[0]  # everyday tools: no load_tools step first


def test_a_workspace_without_playbooks_adds_nothing_to_the_prompt(workspace, model):
    _ask(workspace, "hello")

    assert "Playbook" not in model.systems[0]


def test_an_editor_in_a_workspace_without_playbooks_is_told_how_to_draft_the_first(workspace, model):
    """The bubble's main agent, for someone who may draft: with nothing published it still learns Playbooks exist, so asking it
    to "write a Playbook for our Bench Note voice" works in a fresh workspace."""
    _ask(workspace, "hello", role=WorkspaceRole.EDITOR)

    system = model.systems[0]
    assert "None are published yet" in system
    assert "create_draft" in system


def test_a_workspace_with_only_drafts_adds_nothing_to_the_prompt(workspace, db_session, model):
    _playbook(db_session, workspace.gid, status="draft")

    _ask(workspace, "hello")

    assert "Playbook" not in model.systems[0]


def test_the_catalog_names_this_workspaces_published_playbooks_only(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "mine")
    _playbook(db_session, workspace.gid, "unfinished", status="draft")
    _playbook(db_session, workspace.gid, "retired", status="archived")
    other = _other_workspace(db_session)
    _playbook(db_session, other, "theirs")

    _ask(workspace, "hello")

    system = model.systems[0]
    assert "- mine:" in system
    assert not any(name in system for name in ("unfinished", "retired", "theirs"))


def test_a_long_catalog_is_capped_and_says_where_the_rest_is(workspace, db_session, model):
    from marvin.services.playbooks import CATALOG_MAX

    for i in range(CATALOG_MAX + 2):
        _playbook(db_session, workspace.gid, f"pb-{i:03d}", description="x" * 400)

    _ask(workspace, "hello")

    system = model.systems[0]
    assert system.count("\n- pb-") == CATALOG_MAX
    assert "(2 more: call list_playbooks to see them.)" in system
    assert "x" * 400 not in system  # one line each, not the whole description


# ── The tools ────────────────────────────────────────────────────────────────


def _invoke(workspace, name, args, role=WorkspaceRole.VIEWER) -> dict:
    res = gates._sign_in(workspace, role).post(f"/api/ai/tools/{name}/invoke", json={"args": args})
    assert res.status_code == 200, res.text
    return res.json()


def test_list_playbooks_returns_name_and_description_of_published_ones_in_this_workspace_only(workspace, db_session):
    _playbook(db_session, workspace.gid)
    _playbook(db_session, workspace.gid, "unfinished", status="draft")
    _playbook(db_session, _other_workspace(db_session), "theirs")

    out = _invoke(workspace, "list_playbooks", {})

    assert out == {"playbooks": [{"name": BENCH, "description": BENCH_DESCRIPTION}]}


def test_load_playbook_returns_the_full_text_of_a_published_playbook(workspace, db_session):
    row = _playbook(db_session, workspace.gid)

    out = _invoke(workspace, "load_playbook", {"name": BENCH})

    assert (out["id"], out["name"], out["description"], out["body"]) == (str(row.id), BENCH, BENCH_DESCRIPTION, BENCH_BODY)


@pytest.mark.parametrize("state", ["draft", "inbox", "needs_review", "approved", "archived", "trashed"])
def test_load_playbook_refuses_a_playbook_that_is_not_published(workspace, db_session, state):
    _playbook(db_session, workspace.gid, status=state)

    out = _invoke(workspace, "load_playbook", {"name": BENCH})

    assert "No published Playbook" in out["error"] and "body" not in out and out["available"] == []


def test_load_playbook_refuses_another_workspaces_playbook_and_does_not_say_it_exists(workspace, db_session):
    _playbook(db_session, _other_workspace(db_session), "theirs")
    _playbook(db_session, workspace.gid)

    out = _invoke(workspace, "load_playbook", {"name": "theirs"})

    assert "No published Playbook named 'theirs'" in out["error"]
    assert out["available"] == [BENCH]
    assert "body" not in out


def test_a_refused_load_is_not_recorded_as_a_use(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "unfinished", status="draft")

    run = _ask(workspace, "load playbook unfinished")

    assert "No published Playbook" in json.loads(run["steps"][0]["result"])["error"]
    assert PLAYBOOKS_KEY not in _execution(db_session, run).metadata_json


def test_the_playbook_type_is_made_on_first_use_internal_and_not_publishable(workspace, db_session):
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.playbooks import ensure_playbook_type
    from marvin.services.publish_visibility import is_publishable_type

    def types():
        return db_session.query(EntryTypes).filter_by(group_id=workspace.gid, slug="playbook").all()

    assert types() == []  # reading the catalog never creates it
    _invoke(workspace, "list_playbooks", {})
    assert types() == []

    first = ensure_playbook_type(db_session, workspace.gid)
    assert ensure_playbook_type(db_session, workspace.gid) == first  # once
    (made,) = types()
    assert made.capabilities_json["listed"] is False
    assert is_publishable_type(made) is False
    assert {"name", "description", "body"} <= {f["key"] for f in made.schema_json["fields"]}


# ── Both MCP servers get the tools from the registry ─────────────────────────


def test_the_tools_reach_marvinmcp_through_the_registry(workspace):
    from marvin.services.ai.tools import TOOL_REGISTRY

    assert TOOL_REGISTRY["list_playbooks"].read_only and TOOL_REGISTRY["load_playbook"].read_only
    listed = gates._sign_in(workspace, WorkspaceRole.VIEWER).get("/api/ai/tools").json()  # what MarvinMCP projects as marvin_<name>
    tools = {t["name"]: t for t in listed}

    assert {"list_playbooks", "load_playbook"} <= set(tools)
    assert "mcp" in tools["load_playbook"]["sources"]


def test_the_tools_reach_the_remote_mcp_server_through_the_registry(client, on, ws, db_session):
    owner = ws()
    row = _playbook(db_session, owner.gid)
    _reg, tokens = _connect(client, owner, access="read")  # read-only scope: guidance is a read
    token = tokens["access_token"]
    session = _open_session(client, token)

    listed = _rpc_body(_mcp(client, token, "tools/list", session=session, rpc_id=2))["result"]["tools"]
    assert {"list_playbooks", "load_playbook"} <= {t["name"] for t in listed}

    called = _rpc_body(_mcp(client, token, "tools/call", {"name": "load_playbook", "arguments": {"name": BENCH}}, session=session, rpc_id=3))[
        "result"
    ]
    assert not called.get("isError")
    assert json.loads(called["content"][0]["text"])["id"] == str(row.id)


def _other_workspace(db_session):
    from marvin.db.models.groups import Groups

    slug = f"other-{uuid.uuid4().hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    db_session.add(group)
    db_session.commit()
    return group.id
