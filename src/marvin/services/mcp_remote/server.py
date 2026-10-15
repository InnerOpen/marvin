"""What the remote MCP server offers a signed-in connection: Marvin's registry tools, a few prompts and resources.

Every tool call goes through the shared gateway (`services/ai/tool_gateway.py`), so a connection gets exactly what
the local MarvinMCP gets with a personal token: the tool's role floor, the workspace's "External MCP hosts" switch,
Marvin's permission matrix, the AI budget and the bulk-write gate. The connection's scope narrows it further: a
read-only connection sees and runs read tools only (`is_read_tool`), checked in `tools/list` and again in
`tools/call`. Role and membership are read again on every call, so a demotion counts at once.

The connection (grant, user, workspace, scope) arrives on the HTTP request's state, which the transport sets
(`transport.py`); handlers read it from the SDK's request context. Marvin's DB layer is synchronous, so each call
runs in a worker thread with its own session. See tasks/mcp-oauth-plan.md §4.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

INSTRUCTIONS = (
    "Marvin is a content workspace: entries (typed content such as pages, posts and releases), collections, "
    "assets, reusable resources and workflows. This connection works in one workspace, chosen when it was "
    "approved. Start with search_content or find_entries; workspace_overview describes the workspace. When a "
    "tool returns a reviewLink or URL, give it to the user as is. Write tools make drafts and links; they never "
    "publish, and trashing or archiving a published entry is refused."
)

# Hints only: claude.ai groups tools and asks before the ones that aren't read-only.
DESTRUCTIVE_TOOLS = frozenset({"trash_entries", "archive_entries"})
OPEN_WORLD_TOOLS = frozenset({"import_asset", "run_workflow"})


@dataclass(frozen=True)
class Connection:
    """Who a request to /mcp acts for (set by the transport, read by the handlers)."""

    grant_id: UUID
    user_id: UUID
    group_id: UUID
    can_write: bool


def _connection() -> Connection:
    ctx = server.request_context
    conn = getattr(getattr(ctx.request, "state", None), "mcp_connection", None)
    if conn is None:  # the transport sets it on every request it lets through
        raise RuntimeError("no MCP connection on this request")
    return conn


def _in_thread(fn, *args):
    return anyio.to_thread.run_sync(lambda: fn(*args))


def _with_user(conn: Connection, fn):
    """Run `fn(session, user)` for the connection's user, in its own DB session."""
    from marvin.db.db_setup import session_context
    from marvin.repos.all_repositories import get_repositories

    with session_context() as session:
        user = get_repositories(session, group_id=None).users.get_one(conn.user_id, "id", any_case=False)
        session.commit()  # releases the lazy-load locks (get_current_user does the same)
        if user is None:
            raise PermissionError("This connection's user no longer exists.")
        return fn(session, user)


# ── tools ────────────────────────────────────────────────────────────────────


def clean_schema(schema: Any) -> Any:
    """An input schema every client takes: no `$schema` anywhere (ChatGPT drops tools whose dialect it doesn't
    know: BrainMCP), and always an object."""
    if isinstance(schema, dict):
        return {k: clean_schema(v) for k, v in schema.items() if k != "$schema"}
    if isinstance(schema, list):
        return [clean_schema(v) for v in schema]
    return schema


def _input_schema(spec) -> dict:
    schema = clean_schema(spec.input_schema or {})
    if schema.get("type") != "object":
        return {"type": "object", "properties": {}}
    schema.setdefault("properties", {})
    return schema


def _title(name: str) -> str:
    return re.sub(r"_+", " ", name).strip().capitalize()


def project_tool(spec) -> types.Tool:
    """A registry tool as MCP shows it: the real input schema, no output schema, honest hints."""
    return types.Tool(
        name=spec.name,
        title=_title(spec.name),
        description=spec.description,
        inputSchema=_input_schema(spec),
        annotations=types.ToolAnnotations(
            title=_title(spec.name),
            readOnlyHint=bool(spec.read_only),
            destructiveHint=spec.name in DESTRUCTIVE_TOOLS,
            openWorldHint=spec.name in OPEN_WORLD_TOOLS,
        ),
    )


def list_tools_for(conn: Connection) -> list[types.Tool]:
    from marvin.services.ai.tool_gateway import visible_tools

    return _with_user(conn, lambda session, user: [project_tool(t) for t in visible_tools(session, conn.group_id, user, allow_writes=conn.can_write)])


def call_tool_for(conn: Connection, name: str, args: dict | None) -> dict:
    """The tool's result, or `{"error": …}` for any refusal (the gateway's HTTP refusals included)."""
    from fastapi import HTTPException

    from marvin.services.ai.tool_gateway import invoke_unattended

    def run(session, user):
        try:
            return invoke_unattended(session, conn.group_id, user, name, args or {}, source="mcp", allow_writes=conn.can_write, logger=logger)
        except HTTPException as e:
            return {"error": str(e.detail)}

    return _with_user(conn, run)


def _tool_result(out: dict) -> types.CallToolResult:
    text = json.dumps(out, default=str, ensure_ascii=False)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError="error" in out)


# ── prompts (the local MarvinMCP's, word for word where they still fit) ──────


@dataclass(frozen=True)
class PromptText:
    title: str
    description: str
    lines: tuple[str, ...]


PROMPTS: dict[str, PromptText] = {
    "review_workspace_structure": PromptText(
        "Review Workspace Structure",
        "Inspect Marvin workspace structure and recommend non-destructive improvements.",
        (
            "Review the Marvin workspace structure.",
            "Inspect the workspace, site settings, collections, entries, resources, and entry types.",
            "Identify inconsistent naming, unclear relationships, missing summaries, duplicate structures, and content-model risks.",
            "Recommend changes only; do not mutate content unless the user explicitly asks afterward.",
        ),
    ),
    "create_site_page": PromptText(
        "Create Site Page",
        "Guide creation of a Marvin page draft without automatic publishing.",
        (
            "Help create a Marvin site page.",
            "Inspect available page-like entries and the Page entry type before drafting.",
            "Gather title, slug, summary, body fields, and appropriate collections from the user.",
            "If write tools are unavailable (a read-only connection), produce a draft payload and say so.",
            "Never publish automatically.",
        ),
    ),
    "prepare_release_update": PromptText(
        "Prepare Release Update",
        "Draft a release/update entry for Marvin content workflows.",
        (
            "Prepare a release update.",
            "Inspect existing release or update content first.",
            "Draft content including project, version, significance, maturity, and relevant links.",
            "Create only a draft when write tools are available; do not publish without explicit user intent.",
        ),
    ),
    "audit_content_model": PromptText(
        "Audit Content Model",
        "Audit entries, collections, resources, and site settings for model quality.",
        (
            "Audit the Marvin content model.",
            "Inspect entry types, entries, collections, resources, and site settings.",
            "Find duplicated concepts, ambiguous names, missing relationships, and schema/content mismatches.",
            "Return prioritized recommendations before making any changes.",
        ),
    ),
    "review_collections": PromptText(
        "Review Collections",
        "Review Marvin collection organization and entry grouping.",
        (
            "Review Marvin collections.",
            "Inspect collection names, descriptions, ordering, and entry membership.",
            "Identify duplicated grouping concepts, vague names, empty collections, and missing relationships.",
            "Recommend changes before any mutation.",
        ),
    ),
    "review_assets": PromptText(
        "Review Assets",
        "Review Marvin asset metadata and content usage considerations.",
        (
            "Review Marvin assets.",
            "Inspect asset metadata, file types, alt text, descriptions, and likely content usage.",
            "Identify missing alt text, unclear names, oversized media risks, and duplicate assets.",
            "Do not request or expose binary payloads.",
        ),
    ),
    "review_resources": PromptText(
        "Review Resources",
        "Review reusable Marvin resources and references.",
        (
            "Review Marvin reusable resources.",
            "Inspect resource types, names, descriptions, external IDs, URLs, and metadata.",
            "Identify duplicate references, missing descriptions, stale links, and unclear resource types.",
            "Recommend cleanup before any mutation.",
        ),
    ),
}


# ── resources: each one is a read tool's answer, through the same gateway ────

# uri → (title, description, tool, args)
RESOURCES: dict[str, tuple[str, str, str, dict]] = {
    "marvin://workspace": ("Marvin Workspace", "This connection's workspace: counts, types and recent activity.", "workspace_overview", {}),
    "marvin://collections": ("Marvin Collections", "The workspace's collections.", "list_collections", {}),
    "marvin://resources": ("Marvin Resources", "The workspace's reusable resources.", "list_resources", {}),
    "marvin://entry-types": ("Marvin Entry Types", "The workspace's entry types and their fields.", "list_entry_types", {}),
}
# template → (name, title, description, tool); the template's {slug} becomes the tool's id_or_slug
TEMPLATES: dict[str, tuple[str, str, str, str]] = {
    "marvin://entries/{slug}": ("entry", "Marvin Entry", "A Marvin entry by slug.", "get_entry"),
    "marvin://collections/{slug}": ("collection", "Marvin Collection", "A Marvin collection by slug.", "get_collection"),
    "marvin://resources/{slug}": ("resource", "Marvin Resource", "A reusable Marvin resource by slug.", "get_resource"),
}


def resolve_resource(uri: str) -> tuple[str, dict] | None:
    """The (tool, args) a resource URI reads, or None."""
    if uri in RESOURCES:
        *_, tool, args = RESOURCES[uri]
        return tool, dict(args)
    for template, (*_, tool) in TEMPLATES.items():
        prefix = template.removesuffix("{slug}")
        slug = uri.removeprefix(prefix)
        if uri.startswith(prefix) and slug and "/" not in slug:
            return tool, {"id_or_slug": slug}
    return None


# ── the server ───────────────────────────────────────────────────────────────


def _version() -> str:
    from marvin import __version__

    return __version__


server: Server = Server("Marvin", version=_version(), instructions=INSTRUCTIONS)


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return await _in_thread(list_tools_for, _connection())


@server.call_tool(validate_input=False)
async def _call_tool(name: str, arguments: dict | None) -> types.CallToolResult:
    # validate_input=False: the handlers are lenient about arguments, as /api/ai/tools/{name}/invoke is.
    return _tool_result(await _in_thread(call_tool_for, _connection(), name, arguments))


@server.list_prompts()
async def _list_prompts() -> list[types.Prompt]:
    return [types.Prompt(name=name, title=p.title, description=p.description, arguments=[]) for name, p in PROMPTS.items()]


@server.get_prompt()
async def _get_prompt(name: str, _arguments: dict[str, str] | None) -> types.GetPromptResult:
    prompt = PROMPTS.get(name)
    if prompt is None:
        raise ValueError(f"Unknown prompt: {name}")
    text = types.TextContent(type="text", text="\n".join(prompt.lines))
    return types.GetPromptResult(description=prompt.description, messages=[types.PromptMessage(role="user", content=text)])


@server.list_resources()
async def _list_resources() -> list[types.Resource]:
    return [
        types.Resource(uri=uri, name=uri.removeprefix("marvin://"), title=title, description=desc, mimeType="application/json")
        for uri, (title, desc, _tool, _args) in RESOURCES.items()
    ]


@server.list_resource_templates()
async def _list_resource_templates() -> list[types.ResourceTemplate]:
    return [
        types.ResourceTemplate(uriTemplate=template, name=name, title=title, description=desc, mimeType="application/json")
        for template, (name, title, desc, _tool) in TEMPLATES.items()
    ]


@server.read_resource()
async def _read_resource(uri) -> list[ReadResourceContents]:
    target = resolve_resource(str(uri))
    if target is None:
        raise ValueError(f"Unknown resource: {uri}")
    tool, args = target
    out = await _in_thread(call_tool_for, _connection(), tool, args)
    return [ReadResourceContents(content=json.dumps(out, default=str, ensure_ascii=False), mime_type="application/json")]
