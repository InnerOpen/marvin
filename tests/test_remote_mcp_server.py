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
    own = {"show_image", "search", "fetch"}  # the MCP server's own read tools (the picture itself; ChatGPT's contract)
    assert names and names - own <= read_tools and own <= names
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


# ── show_image ───────────────────────────────────────────────────────────────


def test_show_image_returns_the_picture_itself_scaled_down(client, on, ws, db_session, monkeypatch):
    import base64
    import io
    import uuid

    from PIL import Image

    from marvin.db.models.platform.assets import Assets
    from marvin.services.storage import provider_factory

    owner = ws()
    big = io.BytesIO()
    Image.new("RGB", (3000, 1500), "navy").save(big, format="PNG")
    stored = {"lib/coat": big.getvalue()}

    class FakeStorage:
        def get(self, key):
            return io.BytesIO(stored[key])

        def public_url(self, key):
            return f"https://cdn.test/{key}"

    monkeypatch.setattr(provider_factory, "provider_for", lambda _name=None: FakeStorage())
    slug = f"coat-{uuid.uuid4().hex[:6]}"

    def stored_asset(name, slug_, mime, key):
        return Assets(session=db_session, group_id=owner.gid, slug=slug_, name=name, original_filename=key, filename=key,
                      extension=mime.split("/")[-1],
                      file_size=10, mime_type=mime, asset_type="image", checksum=uuid.uuid4().hex, storage_provider="local", storage_key=key,
                      uploaded_by=owner.uid)  # fmt: skip

    asset = stored_asset("Chore coat", slug, "image/png", "lib/coat")
    svg = stored_asset("Icon", f"{slug}-svg", "image/svg+xml", "lib/icon")
    db_session.add_all([asset, svg])
    db_session.commit()
    try:
        _reg, tokens = _connect(client, owner)
        token = tokens["access_token"]
        session = _open_session(client, token)
        assert "show_image" in {t["name"] for t in _tools(client, token, session)}

        result = _call(client, token, session, "tools/call", {"name": "show_image", "arguments": {"asset": slug}})["result"]
        info, picture = result["content"]
        assert not result.get("isError") and json.loads(info["text"])["name"] == "Chore coat"
        assert picture["type"] == "image" and picture["mimeType"] == "image/jpeg"
        assert Image.open(io.BytesIO(base64.b64decode(picture["data"]))).size == (1024, 512)

        svg_args = {"name": "show_image", "arguments": {"asset": f"{slug}-svg"}}
        result = _call(client, token, session, "tools/call", svg_args, rpc_id=3)["result"]
        assert result["isError"] and len(result["content"]) == 1
        assert "link" in json.loads(result["content"][0]["text"])["error"]  # an SVG: give the user the link
    finally:
        db_session.query(Assets).filter(Assets.group_id == owner.gid).delete()
        db_session.commit()


def test_compose_entry_is_offered_to_read_and_write_connections_only(client, on, ws):
    editor = ws(role=WorkspaceRole.EDITOR)
    _r1, read = _connect(client, editor, access="read")
    _r2, write = _connect(client, editor, access="write")
    read_session, write_session = _open_session(client, read["access_token"]), _open_session(client, write["access_token"])

    assert "compose_entry" not in {t["name"] for t in _tools(client, read["access_token"], read_session)}
    assert "compose_entry" in {t["name"] for t in _tools(client, write["access_token"], write_session)}

    is_error, out = _tool(client, read["access_token"], read_session, "compose_entry", {"entry_type": "page", "brief": "x"})
    assert is_error and (out["error"] == READ_ONLY_REFUSAL or "policy" in out)
    # A write connection reaches the authoring service itself (the test workspace has no AI provider), not a
    # "cannot be invoked from the 'mcp' source" refusal.
    is_error, out = _tool(client, write["access_token"], write_session, "compose_entry", {"entry_type": "page", "brief": "x"})
    assert "source" not in out["error"] and "AI provider" in out["error"]


# ── ChatGPT's search / fetch ─────────────────────────────────────────────────


def test_search_and_fetch_follow_chatgpts_connector_contract(client, on, ws, db_session):
    from marvin.db.models.platform import Entries, EntryTypes

    owner = ws()
    et = EntryTypes(session=db_session, group_id=owner.gid, name="Bench Note", slug="bench-note", schema_json={})
    db_session.add(et)
    db_session.flush()
    entry = Entries(session=db_session, group_id=owner.gid, entry_type_id=et.id, title="Waxed canvas care", slug=f"wax-{owner.gid.hex[:6]}",
                    status="draft", data_json={"body": "Rewax twice a year."})  # fmt: skip
    db_session.add(entry)
    db_session.commit()
    try:
        _reg, tokens = _connect(client, owner, access="read")  # both are read tools: a read-only connection has them
        token = tokens["access_token"]
        session = _open_session(client, token)
        assert {"search", "fetch"} <= {t["name"] for t in _tools(client, token, session)}

        # No AI provider in the test workspace, so no semantic index: search falls back to titles.
        result = _call(client, token, session, "tools/call", {"name": "search", "arguments": {"query": "waxed canvas"}})["result"]
        assert [c["type"] for c in result["content"]] == ["text"]
        hits = json.loads(result["content"][0]["text"])["results"]
        assert hits[0]["id"] == f"entry:{entry.id}" and hits[0]["title"] == "Waxed canvas care" and hits[0]["url"]

        result = _call(client, token, session, "tools/call", {"name": "fetch", "arguments": {"id": hits[0]["id"]}}, rpc_id=3)["result"]
        doc = json.loads(result["content"][0]["text"])
        assert doc["id"] == hits[0]["id"] and doc["title"] == "Waxed canvas care" and "Rewax twice a year." in doc["text"]
        assert doc["url"] and doc["metadata"]["status"] == "draft"

        bad = _call(client, token, session, "tools/call", {"name": "fetch", "arguments": {"id": "nope"}}, rpc_id=4)["result"]
        assert bad["isError"]
    finally:
        db_session.query(Entries).filter(Entries.group_id == owner.gid).delete()
        db_session.query(EntryTypes).filter(EntryTypes.group_id == owner.gid).delete()
        db_session.commit()


def test_a_connection_that_floods_mcp_is_slowed_down(client, on, ws, monkeypatch):
    from marvin.services.mcp_remote import limits

    monkeypatch.setitem(limits.LIMITS, "mcp_request", (3, 60))
    first, second = ws("First"), ws("Second")
    _r1, mine = _connect(client, first)
    _r2, theirs = _connect(client, second)
    session = _open_session(client, mine["access_token"])  # initialize + initialized: 2 requests
    assert _mcp(client, mine["access_token"], "ping", session=session, rpc_id=2).status_code == 200
    limited = _mcp(client, mine["access_token"], "ping", session=session, rpc_id=3)
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1
    assert _mcp(client, theirs["access_token"]).status_code == 200  # per connection, not for everyone
