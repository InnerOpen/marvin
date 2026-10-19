# ruff: noqa: F811, F401 — the `client` / `on` / `ws` fixtures are imported, then named as parameters
"""Remote MCP: the MCP Apps image viewer (`ui://marvin/image-viewer`) that `show_image` points hosts at.

Hosts that support the extension draw the tool result in the conversation; everything else shows the image block as
before. The server's part is metadata plus one resource, checked here the way a client reads it. Whether a particular
host renders it is not testable here (see services/mcp_remote/viewer.py and the manual).
"""

import json
import re

from mcp import types

from marvin.services.mcp_remote import viewer
from tests.test_remote_mcp_oauth import _connect, _open_session, client, on, ws
from tests.test_remote_mcp_server import _call, _tools


def _setup(client, ws, access="read"):
    owner = ws()
    _reg, tokens = _connect(client, owner, access=access)
    token = tokens["access_token"]
    return token, _open_session(client, token)


def test_show_image_names_the_viewer_and_no_other_tool_does(client, on, ws):
    token, session = _setup(client, ws)
    tools = {t["name"]: t for t in _tools(client, token, session)}
    assert tools["show_image"]["_meta"]["ui"]["resourceUri"] == viewer.VIEWER_URI  # the spec's form
    assert tools["show_image"]["_meta"]["ui/resourceUri"] == viewer.VIEWER_URI  # the flat key older hosts read
    assert [name for name, t in tools.items() if "_meta" in t] == ["show_image"]
    types.Tool.model_validate(tools["show_image"])  # still a valid MCP tool


def test_the_viewer_is_a_listed_ui_resource_of_the_right_type(client, on, ws):
    token, session = _setup(client, ws)
    listed = {r["uri"]: r for r in _call(client, token, session, "resources/list")["result"]["resources"]}
    assert listed[viewer.VIEWER_URI]["mimeType"] == "text/html;profile=mcp-app"
    assert viewer.VIEWER_URI.startswith("ui://")

    contents = _call(client, token, session, "resources/read", {"uri": viewer.VIEWER_URI})["result"]["contents"]
    assert len(contents) == 1 and contents[0]["mimeType"] == "text/html;profile=mcp-app"
    assert contents[0]["text"].lstrip().startswith("<!doctype html>")
    assert contents[0]["_meta"] == {"ui": {"prefersBorder": False}}


def test_the_viewer_speaks_the_host_protocol_and_reaches_for_nothing_else(client, on, ws):
    token, session = _setup(client, ws)
    html = _call(client, token, session, "resources/read", {"uri": viewer.VIEWER_URI})["result"]["contents"][0]["text"]
    for needed in ("ui/initialize", "ui/notifications/initialized", "ui/notifications/tool-result", "ui/notifications/size-changed", "ui/open-link"):
        assert needed in html
    assert viewer.PROTOCOL_VERSION in html and "__PROTOCOL_VERSION__" not in html
    # Under the default sandbox CSP (no network, nothing from elsewhere): no external URL, no fetch, no markup injection.
    assert not re.search(r"""(?:src|href)\s*=\s*["']https?://""", html) and "@import" not in html
    for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "innerHTML", "eval(", "document.write"):
        assert banned not in html, banned
    # the picture arrives in the tool result as a data: URL and the page only accepts web links to open
    assert '"data:"' in html and 'u.protocol === "https:"' in html


def test_the_viewer_needs_no_workspace_data_and_works_for_a_read_only_connection(client, on, ws):
    token, session = _setup(client, ws, access="read")
    result = _call(client, token, session, "resources/read", {"uri": viewer.VIEWER_URI})["result"]
    assert "error" not in result and json.dumps(result).count("marvin_") == 0


def test_an_unknown_ui_resource_is_still_refused(client, on, ws):
    token, session = _setup(client, ws)
    body = _call(client, token, session, "resources/read", {"uri": "ui://marvin/other"})
    assert "error" in body


def test_a_client_that_advertises_mcp_apps_is_noted_in_the_log(client, on, ws, caplog):
    import logging

    from tests.test_remote_mcp_oauth import _mcp, _rpc_body

    caplog.set_level(logging.INFO)
    owner = ws()
    _reg, tokens = _connect(client, owner)
    token = tokens["access_token"]
    caps = {"extensions": {viewer.UI_EXTENSION: {"mimeTypes": [viewer.VIEWER_MIME]}}}
    init = _mcp(client, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": caps, "clientInfo": {"name": "t", "version": "1"}})
    session = init.headers["mcp-session-id"]
    _mcp(client, token, "notifications/initialized", session=session, rpc_id=None)
    _rpc_body(_mcp(client, token, "tools/list", session=session, rpc_id=2))
    assert "client advertises MCP Apps: yes" in caplog.text
    caplog.clear()
    plain = _open_session(client, token)
    _tools(client, token, plain)
    assert "client advertises MCP Apps: no" in caplog.text
