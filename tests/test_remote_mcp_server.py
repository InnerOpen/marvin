# ruff: noqa: F811 — the `client` / `on` / `ws` fixtures are imported, then named as parameters
"""Remote MCP slice 3: the tools, prompts and resources at /mcp, and how a connection's scope and session are held
(tasks/mcp-oauth-plan.md §4, §6.2 transport / scope / schemas).

Driven like a real client: sign in through OAuth (the slice 2 helpers), open an MCP session over streamable HTTP, call.
"""

import json

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.tool_gateway import READ_ONLY_REFUSAL, is_read_tool
from marvin.services.ai.tools import list_tools
from tests.test_remote_mcp_oauth import _connect, _mcp, _open_session, _rpc_body, client, on, ws  # noqa: F401 — fixtures


def _call(client, token, session, method, params=None, rpc_id=2) -> dict:
    return _rpc_body(_mcp(client, token, method, params, session=session, rpc_id=rpc_id))


def _tools(client, token, session) -> list[dict]:
    return _call(client, token, session, "tools/list")["result"]["tools"]


def _tool(client, token, session, name, args=None) -> tuple[bool, dict]:
    result = _call(client, token, session, "tools/call", {"name": name, "arguments": args or {}})["result"]
    return result.get("isError", False), json.loads(result["content"][0]["text"])


def _all_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _all_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _all_keys(v)}
    return set()


# ── scope ────────────────────────────────────────────────────────────────────


def test_a_read_only_connection_sees_and_runs_read_tools_only(client, on, ws):
    owner = ws()
    _reg, tokens = _connect(client, owner, access="read")
    token = tokens["access_token"]
    session = _open_session(client, token)

    names = {t["name"] for t in _tools(client, token, session)}
    read_tools = {t.name for t in list_tools() if "mcp" in t.sources and is_read_tool(t)}
    assert names and names <= read_tools
    assert {"find_entries", "get_entry", "workspace_overview"} <= names

    # Pinned against the whole registry: every tool that isn't a read tool is refused, listed or not — by the
    # connection's scope, or earlier by Marvin's matrix ("Ask first" can't pause here; that refusal names its policy).
    for spec in list_tools():
        if "mcp" in spec.sources and not is_read_tool(spec):
            is_error, out = _tool(client, token, session, spec.name)
            assert is_error and (out["error"] == READ_ONLY_REFUSAL or "policy" in out), spec.name


def test_a_read_and_write_connection_gets_the_write_tools_under_the_matrix(client, on, ws, db_session):
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    editor = ws(role=WorkspaceRole.EDITOR)
    _reg, tokens = _connect(client, editor, access="write")
    token = tokens["access_token"]
    session = _open_session(client, token)
    names = {t["name"] for t in _tools(client, token, session)}
    assert {"attach_tag", "revise_entry", "find_entries"} <= names

    # Demoted to Viewer mid-connection: the next call reads the role again, and writes stop.
    db_session.query(WorkspaceMembers).filter_by(user_id=editor.uid, group_id=editor.gid).update({"workspace_role": WorkspaceRole.VIEWER})
    db_session.commit()
    assert "attach_tag" not in {t["name"] for t in _tools(client, token, session)}
    is_error, out = _tool(client, token, session, "attach_tag", {"entry": "x", "tag": "y"})
    assert is_error and "error" in out


def test_a_read_tool_answers_with_the_workspace(client, on, ws):
    owner = ws()
    _reg, tokens = _connect(client, owner)
    session = _open_session(client, tokens["access_token"])
    is_error, out = _tool(client, tokens["access_token"], session, "list_collections")
    assert not is_error and "error" not in out


# ── what the tool list looks like to a client ────────────────────────────────


def test_tool_schemas_are_ones_every_client_takes(client, on, ws):
    owner = ws()
    _reg, tokens = _connect(client, owner, access="write")
    tools = _tools(client, tokens["access_token"], _open_session(client, tokens["access_token"]))
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names))
    for t in tools:
        assert "outputSchema" not in t, t["name"]  # ChatGPT drops tools it can't read (BrainMCP)
        assert "$schema" not in _all_keys(t["inputSchema"]), t["name"]
        assert t["inputSchema"]["type"] == "object", t["name"]
        assert t["annotations"]["readOnlyHint"] in (True, False)
    hints = {t["name"]: t["annotations"] for t in tools}
    assert hints["trash_entries"]["destructiveHint"] is True and hints["find_entries"]["readOnlyHint"] is True


def test_prompts_and_resources_answer(client, on, ws):
    owner = ws()
    _reg, tokens = _connect(client, owner)
    token = tokens["access_token"]
    session = _open_session(client, token)

    prompts = _call(client, token, session, "prompts/list")["result"]["prompts"]
    assert len(prompts) == 7 and "review_workspace_structure" in {p["name"] for p in prompts}
    got = _call(client, token, session, "prompts/get", {"name": "review_collections"})["result"]
    assert got["messages"][0]["content"]["text"].startswith("Review Marvin collections.")

    uris = {r["uri"] for r in _call(client, token, session, "resources/list")["result"]["resources"]}
    assert "marvin://workspace" in uris
    templates = {t["uriTemplate"] for t in _call(client, token, session, "resources/templates/list")["result"]["resourceTemplates"]}
    assert "marvin://entries/{slug}" in templates
    contents = _call(client, token, session, "resources/read", {"uri": "marvin://collections"})["result"]["contents"]
    assert contents[0]["mimeType"] == "application/json" and "error" not in json.loads(contents[0]["text"])


# ── sessions ─────────────────────────────────────────────────────────────────


def test_a_session_belongs_to_the_connection_that_opened_it(client, on, ws):
    first, second = ws("First"), ws("Second")
    _r1, mine = _connect(client, first)
    _r2, theirs = _connect(client, second)
    session = _open_session(client, mine["access_token"])

    hijack = _mcp(client, theirs["access_token"], "tools/list", session=session, rpc_id=2)
    assert hijack.status_code == 403
    assert _mcp(client, None, "tools/list", session=session, rpc_id=2).status_code == 401  # POST always needs a token

    # DELETE (like GET) may come without a token on a live session; afterwards the session is gone.
    assert client.delete("/mcp", headers={"mcp-session-id": session}).status_code == 200
    assert client.delete("/mcp", headers={"mcp-session-id": session}).status_code == 401
    assert _mcp(client, mine["access_token"], "tools/list", session=session, rpc_id=3).status_code == 404  # start again


def test_a_workspace_that_turns_mcp_off_stops_its_connections(client, on, ws, db_session):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    owner = ws()
    _reg, tokens = _connect(client, owner)
    session = _open_session(client, tokens["access_token"])
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=owner.gid, invocation_sources={"mcp": False}))
    db_session.commit()
    try:
        res = _mcp(client, tokens["access_token"], "tools/list", session=session, rpc_id=2)
        assert res.status_code == 403 and "turned off" in res.json()["error_description"]
    finally:
        db_session.query(WorkspaceAISettingsModel).filter_by(group_id=owner.gid).delete()
        db_session.commit()
