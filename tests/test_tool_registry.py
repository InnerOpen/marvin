"""Unit tests for the core AI tool registry (services/ai/tools/base.py).

Covers the registry mechanics — register/list/get, info() projection, and the role/source
filtering the agent binding and the /tools endpoints rely on — without a DB or provider.
"""

import pytest

from marvin.services.ai.operations.base import ROLE_ADMIN, ROLE_VIEWER
from marvin.services.ai.tools.base import (
    INVOCATION_SOURCES,
    TOOL_REGISTRY,
    ToolContext,
    get_tool,
    list_tools,
    register_tool,
)


def test_builtins_are_registered():
    # Importing the package registers the built-in tools.
    import marvin.services.ai.tools  # noqa: F401

    names = {t.name for t in list_tools()}
    assert {
        "search_content",
        "find_entries",
        "get_entry",
        "get_collection",
        "get_resource",
        "get_entry_type",
        "list_collections",
        "get_collection_entries",
        "list_resources",
        "list_entry_types",
        "list_assets",
        "get_asset",
    } <= names
    # Authoring tools now go through the registry (shared AuthoringService, one door):
    # compose_entry (agent-bound; withholds the mcp source to avoid colliding with the hand-wired
    # marvin_compose_entry) and revise_entry (also projects to MCP).
    assert {"compose_entry", "revise_entry"} <= names


def test_insights_tools_are_registered_and_projected():
    # The insights surface (executions/events/tasks) moved out of MarvinMCP into the registry, so the
    # agent binds them in-process AND MarvinMCP projects them (they must declare the "mcp" source).
    import marvin.services.ai.tools  # noqa: F401
    from marvin.services.ai.tools import get_tool, list_tools

    insights = {
        "list_ai_executions",
        "get_ai_execution",
        "get_ai_settings",
        "list_events",
        "get_entity_history",
        "list_scheduled_tasks",
        "get_scheduled_task_history",
    }
    names = {t.name for t in list_tools()}
    assert insights <= names
    for n in insights:
        spec = get_tool(n)
        assert "mcp" in spec.sources and "agent" in spec.sources  # projected AND agent-bound
        assert spec.read_only is True


def test_register_and_get_roundtrip():
    @register_tool(
        name="_probe_tool",
        description="probe",
        input_schema={"type": "object", "properties": {}},
        min_role=ROLE_ADMIN,
        sources=("mcp",),
        read_only=False,
    )
    def _probe(ctx: ToolContext, args: dict) -> str:
        return "ok"

    try:
        spec = get_tool("_probe_tool")
        assert spec.min_role == ROLE_ADMIN
        assert spec.sources == ("mcp",)
        assert spec.read_only is False
        assert spec.handler(None, {}) == "ok"
    finally:
        TOOL_REGISTRY.pop("_probe_tool", None)


def test_get_unknown_tool_raises():
    with pytest.raises(KeyError):
        get_tool("does_not_exist")


def test_info_shape_matches_projection_contract():
    spec = get_tool("get_entry")
    info = spec.info()
    assert set(info) == {"name", "description", "input_schema", "min_role", "sources", "read_only"}
    assert info["name"] == "get_entry"
    assert isinstance(info["sources"], list)


def test_default_source_is_all_and_read_tools_are_viewer():
    # Built-in read tools default to all sources and VIEWER role (readable content surfaces).
    spec = get_tool("list_collections")
    assert tuple(spec.sources) == INVOCATION_SOURCES
    assert spec.min_role == ROLE_VIEWER
    assert spec.read_only is True
