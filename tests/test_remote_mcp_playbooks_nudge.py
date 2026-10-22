"""Outside MCP clients are told the workspace keeps Playbooks and which tools load them (they get no catalog in
their instructions, unlike Marvin's own agents)."""

from marvin.services.mcp_remote.server import INSTRUCTIONS
from marvin.services.playbooks import LIST_TOOL, LOAD_TOOL


def test_the_connector_instructions_point_outside_assistants_at_the_playbook_tools():
    assert "Playbooks" in INSTRUCTIONS
    assert LIST_TOOL in INSTRUCTIONS and LOAD_TOOL in INSTRUCTIONS  # the names the tools are registered under


def test_list_playbooks_no_longer_claims_a_catalog_outside_clients_do_not_have():
    import marvin.services.ai.tools.builtins_playbooks  # noqa: F401 — registers the tools
    from marvin.services.ai.tools.base import get_tool

    description = get_tool(LIST_TOOL).description
    assert "the catalog in your instructions is the same list" not in description
    assert LOAD_TOOL in description
