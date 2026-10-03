"""External MCP tools: slow servers get time, huge results are cut, and no agent passes off workspace search as one.

Regression (Grace's workspace, asking "check the brain"): the router handed the question to Ask, which can
only search the workspace — it did, and answered as if it had read the Brain vault. On the retry the Brain's
vault search took ~21 s against a 20 s per-call timeout, so every call failed, and a broad search returns
~400 KB that would have gone to the model whole.
"""

import json
import logging
from types import SimpleNamespace

from marvin.core.config import get_app_settings
from marvin.routes.ai import operations_controller as oc
from marvin.services.ai import mcp_client
from marvin.services.ai.agents import SOURCE_HONESTY_RULE, workspace_preamble
from marvin.services.ai.mcp_client import McpToolInfo, clip_result


def test_clip_result_leaves_a_short_result_alone():
    assert clip_result("small", 10) == "small"


def test_clip_result_cuts_a_long_result_and_says_how_to_see_the_rest():
    out = clip_result("x" * 50, 10)

    assert out.startswith("x" * 10 + "\n\n[Result truncated: showing 10 of 50 characters.")
    assert "Narrow the call" in out


def test_an_agent_with_external_sources_answers_about_them_itself():
    text = workspace_preamble("W", ["search_content", "run_agent", "mcp__brain__search-vault"])

    assert "do not hand the question to another agent unless the user names that agent" in text
    assert SOURCE_HONESTY_RULE not in text


def test_an_agent_without_external_sources_says_it_cannot_reach_them():
    assert SOURCE_HONESTY_RULE in workspace_preamble("W", ["search_content", "workspace_overview", "suggest_agent"])
    assert SOURCE_HONESTY_RULE not in workspace_preamble("W", [])  # a tool-less model agent has its own prompt


# --- the bound tool ---------------------------------------------------------------------------------


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter_by(self, **_):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


def _controller(monkeypatch, result_text=None, error=None):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    server = SimpleNamespace(slug="the-brain", name="The Brain", allowed_tools=["search-vault"], group_id="g")
    rows = {WorkspaceAISettingsModel: [SimpleNamespace(external_mcp_enabled=True)]}
    session = SimpleNamespace(query=lambda model: _Query(rows.get(model, [server])))
    for name, value in (("session", session), ("group_id", "g"), ("logger", logging.getLogger("test"))):
        monkeypatch.setattr(oc.AIOperationsController, name, property(lambda self, v=value: v), raising=False)
    ctl = object.__new__(oc.AIOperationsController)
    calls = []
    monkeypatch.setattr(mcp_client, "list_server_tools", lambda s, timeout: [McpToolInfo("search-vault", "Search", {}, read_only=True)])

    def call(s, name, args, timeout):
        calls.append(timeout)
        if error:
            raise error
        return result_text, False

    monkeypatch.setattr(mcp_client, "call_server_tool", call)
    (tool,) = ctl._external_mcp_tools()
    return tool, calls


def test_a_tool_call_waits_the_configured_timeout(monkeypatch):
    tool, calls = _controller(monkeypatch, result_text="ok")

    assert tool.run({"query": "today"}) == "ok"
    assert calls == [get_app_settings().MCP_TOOL_TIMEOUT_SECONDS]


def test_a_huge_result_reaches_the_model_cut_to_the_configured_size(monkeypatch):
    limit = get_app_settings().MCP_TOOL_RESULT_MAX_CHARS
    tool, _ = _controller(monkeypatch, result_text="y" * (limit * 20))

    out = tool.run({"query": "today"})

    assert out.startswith("y" * limit + "\n\n[Result truncated")
    assert len(out) < limit + 300


def test_a_failed_call_is_an_error_for_the_model_not_a_crash(monkeypatch):
    tool, _ = _controller(monkeypatch, error=mcp_client.McpClientError("timed out connecting to the server"))

    assert json.loads(tool.run({"query": "today"})) == {"error": "timed out connecting to the server"}
