"""
Tool categories — the rows of an agent's permission matrix.

Every tool an agent can bind belongs to exactly one category: registry tools by name (below),
AI operations to `ai_ops`, external MCP tools to `mcp`. A category says whether its actions write.
The matrix is data-driven from this file plus the registry, so a new tool only needs a line here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolCategory:
    id: str
    label: str
    writes: bool
    description: str


CATEGORIES: tuple[ToolCategory, ...] = (
    ToolCategory("entries_read", "Entries: read", False, "Search and read entries, entry types and history"),
    ToolCategory("entries_author", "Entries: author", True, "Compose and revise entries (always as drafts for review)"),
    ToolCategory("links", "Links", True, "Attach or detach tags, assets and resources; add to or remove from collections"),
    ToolCategory("library_read", "Library: read", False, "List and read collections, resources, tags and assets"),
    ToolCategory("assets_import", "Assets: import", True, "Import files as assets"),
    ToolCategory("automation_read", "Automation: read", False, "Events, scheduled tasks and their history"),
    ToolCategory("automation_run", "Automation: run", True, "Trigger workflows"),
    ToolCategory("insights", "AI insights", False, "AI executions and settings"),
    ToolCategory("agents_read", "Agents: read", False, "List the workspace's agents"),
    ToolCategory("agents_run", "Agents: delegate", True, "Run another agent on the caller's behalf"),
    ToolCategory("ai_ops", "AI operations", True, "LLM generations with write-back: summaries, tags, alt text, rewrites"),
    ToolCategory("mcp", "External MCP tools", True, "Tools from connected MCP servers"),
    ToolCategory("other_read", "Other: read", False, "Read-only tools not yet categorised"),
    ToolCategory("other_write", "Other: write", True, "Writing tools not yet categorised"),
)
CATEGORY_BY_ID: dict[str, ToolCategory] = {c.id: c for c in CATEGORIES}

CATEGORY_BY_TOOL: dict[str, str] = {
    "search_content": "entries_read",
    "find_entries": "entries_read",
    "get_entry": "entries_read",
    "list_entry_types": "entries_read",
    "get_entry_type": "entries_read",
    "get_entity_history": "entries_read",
    "compose_entry": "entries_author",
    "revise_entry": "entries_author",
    "attach_tag": "links",
    "detach_tag": "links",
    "attach_asset": "links",
    "detach_asset": "links",
    "attach_resource": "links",
    "detach_resource": "links",
    "add_to_collection": "links",
    "remove_from_collection": "links",
    "list_collections": "library_read",
    "get_collection": "library_read",
    "get_collection_entries": "library_read",
    "list_resources": "library_read",
    "get_resource": "library_read",
    "list_tags": "library_read",
    "list_assets": "library_read",
    "get_asset": "library_read",
    "import_asset": "assets_import",
    "list_events": "automation_read",
    "list_scheduled_tasks": "automation_read",
    "get_scheduled_task_history": "automation_read",
    "run_workflow": "automation_run",
    "get_ai_execution": "insights",
    "list_ai_executions": "insights",
    "get_ai_settings": "insights",
    "list_agents": "agents_read",
    "run_agent": "agents_run",
}


def category_of(name: str, *, read_only: bool | None = None) -> str:
    """Category id for a bound tool name. Unknown registry tools fall back on their read_only flag."""
    if name in CATEGORY_BY_TOOL:
        return CATEGORY_BY_TOOL[name]
    if name.startswith("mcp__"):
        return "mcp"
    if read_only is None:
        return "other_write"
    return "other_read" if read_only else "other_write"


def category_writes(category_id: str) -> bool:
    cat = CATEGORY_BY_ID.get(category_id)
    return True if cat is None else cat.writes
