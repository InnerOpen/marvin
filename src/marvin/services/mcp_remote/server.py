"""What the remote MCP server offers a signed-in connection: Marvin's registry tools, a few prompts and resources.

Every tool call goes through the shared gateway (`services/ai/tool_gateway.py`), so a connection gets exactly what
the local MarvinMCP gets with a personal token: the tool's role floor, the workspace's "External MCP hosts" switch,
the External assistants permission matrix, the AI budget and the bulk-write gate. The connection's scope narrows it further: a
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
from marvin.services.mcp_remote import uploads, viewer

logger = get_logger(__name__)

INSTRUCTIONS = (
    "Marvin is a content workspace: entries (typed content such as pages, posts and releases), collections, "
    "assets, reusable resources and workflows. This connection works in one workspace, chosen when it was "
    "approved. Start with search (or find_entries); workspace_overview describes the workspace. Whenever "
    "you mention an entry or an asset that a tool gave a `url` or `reviewLink` for, include that link as is so "
    "the user can open it. To show the user an image asset, call show_image: it returns the picture itself "
    "(view_image only describes one in words). To create or change an entry, write it yourself and save it "
    "with create_draft / update_draft (get_entry_type first, for the fields); compose_entry and revise_entry "
    "have Marvin's own AI do the writing instead. A photo in the chat can't be passed to a tool: call upload_link, "
    "give the user the link to open, then call check_upload with its linkId to get the new asset. Write tools make "
    "drafts and links; they never publish, and trashing or archiving a published entry is refused."
)

# Registry tools the remote server offers although they withhold the `mcp` source: compose_entry stays off the
# local MarvinMCP's list (it has its own marvin_compose_entry), but a remote connection has no other way to create.
EXTRA_TOOLS = ("compose_entry",)

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


def _has_semantic_search(session, group_id) -> bool:
    """Whether the workspace has an embedding model: its AI provider's, or Marvin's built-in one."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.embeddings import embedding_model_for_settings

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    return bool(embedding_model_for_settings(settings.provider if settings else None))


def list_tools_for(conn: Connection) -> list[types.Tool]:
    from marvin.services.ai.tool_gateway import visible_tools

    def run(session, user):
        listed = visible_tools(session, conn.group_id, user, allow_writes=conn.can_write, extra=EXTRA_TOOLS)
        if not _has_semantic_search(session, conn.group_id):  # it would only answer "unavailable"; `search` falls back
            listed = [t for t in listed if t.name != "search_content"]
        # An upload link follows import_asset's rules (write scope, Editor, the External assistants matrix): shown when that tool is.
        uploading = [UPLOAD_LINK, CHECK_UPLOAD] if any(t.name == uploads.TOOL for t in listed) else []
        return [*(project_tool(t) for t in listed), *uploading, SHOW_IMAGE, SEARCH, FETCH]

    return _with_user(conn, run)


def call_tool_for(conn: Connection, name: str, args: dict | None) -> dict:
    """The tool's result, or `{"error": …}` for any refusal (the gateway's HTTP refusals included)."""
    from fastapi import HTTPException

    from marvin.services.ai.tool_gateway import invoke_unattended

    def run(session, user):
        try:
            return invoke_unattended(
                session, conn.group_id, user, name, args or {}, source="mcp", allow_writes=conn.can_write, extra=EXTRA_TOOLS, logger=logger
            )
        except HTTPException as e:
            return {"error": str(e.detail)}

    return _with_user(conn, run)


# ── show_image: the picture itself, which only an MCP client can take (registry tools answer in text) ──

SHOW_IMAGE_SIDE = 1024  # px on the long side: plenty to look at, small enough for any client
SHOWABLE = frozenset({"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"})
SHOW_IMAGE = types.Tool(
    name="show_image",
    title="Show image",
    description=(
        "Show an image asset itself, so you and the user can see it (view_image only describes it in words). Returns "
        f"the picture, scaled to at most {SHOW_IMAGE_SIDE} px, with its name and link. JPEG, PNG, WebP and GIF; for other "
        "files (SVG, PDF…) give the user the link."
    ),
    inputSchema={"type": "object", "properties": {"asset": {"type": "string", "description": "asset id or slug"}}, "required": ["asset"]},
    annotations=types.ToolAnnotations(title="Show image", readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    _meta=viewer.TOOL_META,  # MCP Apps: a host that supports it draws the result in the conversation (viewer.py)
)


def show_image_for(conn: Connection, args: dict | None) -> tuple[dict, str | None, str | None]:
    """(info or {"error"}, base64 picture, its mime type) for an image asset in the connection's workspace."""

    def run(session, _user):
        import base64
        import io
        import uuid

        from PIL import Image

        from marvin.db.models.platform.assets import Assets
        from marvin.services.ai.entity_resolve import resolve_entity_id
        from marvin.services.ai.media.transforms import _load
        from marvin.services.ai.tools.builtins import _asset_public_url
        from marvin.services.assets.scope import is_playbook_file
        from marvin.services.storage.provider_factory import provider_for

        ref = str((args or {}).get("asset") or "").strip()
        asset_id = resolve_entity_id(session, conn.group_id, "asset", ref) if ref else None
        asset = session.get(Assets, asset_id) if isinstance(asset_id, uuid.UUID) else None
        if asset is None or str(asset.group_id) != str(conn.group_id) or asset.trashed_at is not None or is_playbook_file(asset):
            return {"error": f"no asset '{ref}' in this workspace (try list_assets)"}, None, None
        info = {
            "id": str(asset.id),
            "name": asset.name,
            "altText": asset.alt_text or None,
            "mimeType": asset.mime_type,
            "url": _asset_public_url(asset),
        }
        if (asset.mime_type or "").lower() not in SHOWABLE:
            return {**info, "error": "not a picture Marvin can show here; give the user the link"}, None, None
        try:
            img, _fmt = _load(provider_for(asset.storage_provider).get(asset.storage_key).read())
        except Exception as e:  # noqa: BLE001 — a missing or broken file is an answer, not a crash
            return {**info, "error": f"the file could not be read: {e}"}, None, None
        img.thumbnail((SHOW_IMAGE_SIDE, SHOW_IMAGE_SIDE), Image.Resampling.LANCZOS)
        transparent = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        out = io.BytesIO()
        if transparent:
            img.convert("RGBA").save(out, format="PNG", optimize=True)
            mime = "image/png"
        else:
            img.convert("RGB").save(out, format="JPEG", quality=85, optimize=True)
            mime = "image/jpeg"
        return {**info, "width": img.width, "height": img.height}, base64.b64encode(out.getvalue()).decode("ascii"), mime

    return _with_user(conn, run)


# ── upload_link / check_upload: how a photo in the chat reaches Marvin (uploads.py) ──

UPLOAD_LINK = types.Tool(
    name="upload_link",
    title="Upload link",
    description=(
        "Get a one-time link where the user can upload a photo from their phone or computer into this workspace's asset "
        f"library, for when a photo in the chat can't be passed to you. Give the user the link as is (open it, choose one "
        f"photo, Upload); it works once, for {uploads.LINK_MINUTES} minutes, for one file. Then call check_upload with the "
        "returned linkId to get the new asset. Optionally name the asset and give its alt text."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "display name for the new asset (default: the file's name)"},
            "alt_text": {"type": "string", "description": "alt text for the new asset"},
        },
    },
    annotations=types.ToolAnnotations(title="Upload link", readOnlyHint=False, destructiveHint=False, openWorldHint=False),
)
CHECK_UPLOAD = types.Tool(
    name="check_upload",
    title="Check upload",
    description=(
        "Whether the user has uploaded the photo for an upload_link yet: waiting, uploaded (with the new asset: id, slug, "
        "name, link), expired or failed. Ask the user to finish the upload first, then call this; it is safe to repeat."
    ),
    inputSchema={
        "type": "object",
        "properties": {"link_id": {"type": "string", "description": "the linkId upload_link returned"}},
        "required": ["link_id"],
    },
    annotations=types.ToolAnnotations(title="Check upload", readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)


def upload_link_for(conn: Connection, args: dict | None, base_url: str, ip: str | None) -> dict:
    from marvin.services.mcp_remote import limits

    args = args or {}

    def run(session, user):
        try:
            limits.check("upload_link", str(conn.grant_id))
        except limits.RateLimited as e:
            return {"error": f"too many upload links; try again in {e.retry_after} seconds"}
        try:
            row, secret = uploads.create_link(session, conn, user, name=str(args.get("name") or ""), alt_text=str(args.get("alt_text") or ""), ip=ip)
        except uploads.UploadError as e:
            return {"error": e.message}
        limits.hit("upload_link", str(conn.grant_id))
        return {
            "url": uploads.page_url(base_url, secret),
            "linkId": str(row.id),
            "expiresInMinutes": uploads.LINK_MINUTES,
            "next": "Give the user this link to open and upload one photo. Then call check_upload with the linkId.",
        }

    return _with_user(conn, run)


def check_upload_for(conn: Connection, args: dict | None) -> dict:
    from marvin.services.ai.tools.builtins import _asset_public_url

    def run(session, _user):
        out = uploads.status_of(session, conn, str((args or {}).get("link_id") or ""))
        asset = out.pop("asset", None)
        if asset is not None:
            out["asset"] = {
                "id": str(asset.id),
                "slug": asset.slug,
                "name": asset.name,
                "mimeType": asset.mime_type,
                "width": asset.width,
                "height": asset.height,
                "url": _admin_url("asset", str(asset.id)),
                "publicUrl": _asset_public_url(asset),
            }
            out["next"] = "show_image looks at it; attach_asset puts it on an entry."
        return out

    return _with_user(conn, run)


# ── search / fetch: the two tools ChatGPT uses outside developer mode (its connector contract) ──

KINDS = ("entry", "asset", "resource")
ADMIN_PATHS = {"entry": "/workspace/entries/{id}", "asset": "/workspace/assets/{id}", "resource": "/workspace/resources/{id}"}
SEARCH_RESULTS = 10
FETCH_TEXT_CHARS = 20_000

_READ_HINTS = types.ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
SEARCH = types.Tool(
    name="search",
    title="Search",
    description="Search this Marvin workspace's entries, assets and resources. Returns results with an id to pass to fetch.",
    inputSchema={"type": "object", "properties": {"query": {"type": "string", "description": "what to look for"}}, "required": ["query"]},
    annotations=_READ_HINTS,
)
FETCH = types.Tool(
    name="fetch",
    title="Fetch",
    description="Fetch one search result in full by its id (entry:<id>, asset:<id> or resource:<id>).",
    inputSchema={"type": "object", "properties": {"id": {"type": "string", "description": "an id from search"}}, "required": ["id"]},
    annotations=_READ_HINTS,
)


def _admin_url(kind: str, entity_id: str) -> str:
    from marvin.services.ui_links import ui_link

    return ui_link(ADMIN_PATHS[kind].format(id=entity_id))


def search_for(conn: Connection, args: dict | None) -> dict:
    """{"results": [{id, title, url}]}: semantic search, or a title search when the workspace has none."""
    query = str((args or {}).get("query") or "").strip()
    if not query:
        return {"results": []}
    out = call_tool_for(conn, "search_content", {"query": query})
    results, seen = [], set()
    for r in [] if "error" in out else out.get("results", []):
        kind, entity_id = r.get("entityType"), r.get("entityId")
        key = f"{kind}:{entity_id}"
        if kind in KINDS and entity_id and key not in seen:
            seen.add(key)
            results.append({"id": key, "title": r.get("title") or key, "url": r.get("url") or _admin_url(kind, entity_id)})
    if not results:  # no semantic index here (or nothing in it): fall back to titles and slugs
        found = call_tool_for(conn, "find_entries", {"query": query, "limit": SEARCH_RESULTS})
        for e in found.get("entries", []):
            results.append({"id": f"entry:{e['id']}", "title": e.get("title") or e.get("slug"), "url": e.get("url") or _admin_url("entry", e["id"])})
    return {"results": results[:SEARCH_RESULTS]}


def fetch_for(conn: Connection, args: dict | None) -> dict:
    """{id, title, text, url, metadata} for an id from search."""
    ident = str((args or {}).get("id") or "").strip()
    kind, _, entity_id = ident.partition(":")
    if kind not in KINDS or not entity_id:
        return {"error": "id must look like entry:<id>, asset:<id> or resource:<id> (as search returns)"}
    out = call_tool_for(conn, f"get_{kind}", {"id_or_slug": entity_id})
    if "error" in out:
        return out
    item = out.get(kind, out)  # get_entry answers with the entry itself; others may wrap it
    title = item.get("title") or item.get("name") or ident
    text = json.dumps(item, default=str, ensure_ascii=False)[:FETCH_TEXT_CHARS]
    metadata = {k: item.get(k) for k in ("status", "entryType", "assetType", "resourceType", "updatedAt") if item.get(k) is not None}
    return {"id": ident, "title": title, "text": text, "url": item.get("url") or _admin_url(kind, entity_id), "metadata": metadata}


CONNECTOR_TOOLS = {SEARCH.name: search_for, FETCH.name: fetch_for}


def _connector_result(out: dict) -> types.CallToolResult:
    """The connector contract: one text block holding the JSON (no structured content, which ChatGPT reads as {})."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(out, default=str, ensure_ascii=False))], isError="error" in out
    )


def _image_result(info: dict, data: str | None, mime: str | None) -> types.CallToolResult:
    text = types.TextContent(type="text", text=json.dumps(info, default=str, ensure_ascii=False))
    if data is None:
        return types.CallToolResult(content=[text], isError=True)
    return types.CallToolResult(content=[text, types.ImageContent(type="image", data=data, mimeType=mime)], isError=False)


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


def _client_has_ui() -> bool:
    """Whether the client's `initialize` advertised the MCP Apps extension (logged, so a real connection shows whether
    its host can draw the image viewer; the metadata is sent either way)."""
    try:
        caps = server.request_context.session.client_params.capabilities
        return viewer.UI_EXTENSION in ((getattr(caps, "model_extra", None) or {}).get("extensions") or {})
    except Exception:  # noqa: BLE001 — a log detail, never worth failing tools/list
        return False


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    tools = await _in_thread(list_tools_for, _connection())
    logger.info("remote MCP tools/list → %d tools (client advertises MCP Apps: %s)", len(tools), "yes" if _client_has_ui() else "no")
    return tools


@server.call_tool(validate_input=False)
async def _call_tool(name: str, arguments: dict | None) -> types.CallToolResult:
    # validate_input=False: the handlers are lenient about arguments, as /api/ai/tools/{name}/invoke is.
    if name == SHOW_IMAGE.name:
        result = _image_result(*await _in_thread(show_image_for, _connection(), arguments))
    elif name == UPLOAD_LINK.name:
        request = server.request_context.request
        from marvin.services.mcp_remote.policy import issuer
        from marvin.services.security.login_throttle import login_client_ip

        result = _tool_result(await _in_thread(upload_link_for, _connection(), arguments, issuer(request), login_client_ip(request)))
    elif name == CHECK_UPLOAD.name:
        result = _tool_result(await _in_thread(check_upload_for, _connection(), arguments))
    elif name in CONNECTOR_TOOLS:
        result = _connector_result(await _in_thread(CONNECTOR_TOOLS[name], _connection(), arguments))
    else:
        result = _tool_result(await _in_thread(call_tool_for, _connection(), name, arguments))
    # Which tool, and what went back (never the arguments or the content).
    logger.info("remote MCP tools/call %s → %s [%s]", name, "error" if result.isError else "ok", ",".join(c.type for c in result.content))
    return result


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
    listed = [
        types.Resource(uri=uri, name=uri.removeprefix("marvin://"), title=title, description=desc, mimeType="application/json")
        for uri, (title, desc, _tool, _args) in RESOURCES.items()
    ]
    # The page show_image's result is drawn in, by hosts that support MCP Apps (no data of the workspace in it).
    listed.append(
        types.Resource(
            uri=viewer.VIEWER_URI,
            name="image-viewer",
            title="Marvin image viewer",
            description="Draws show_image's picture in the conversation.",
            mimeType=viewer.VIEWER_MIME,
        )
    )
    return listed


@server.list_resource_templates()
async def _list_resource_templates() -> list[types.ResourceTemplate]:
    return [
        types.ResourceTemplate(uriTemplate=template, name=name, title=title, description=desc, mimeType="application/json")
        for template, (name, title, desc, _tool) in TEMPLATES.items()
    ]


@server.read_resource()
async def _read_resource(uri) -> list[ReadResourceContents]:
    if str(uri) == viewer.VIEWER_URI:
        return [ReadResourceContents(content=viewer.VIEWER_HTML, mime_type=viewer.VIEWER_MIME, meta={"ui": {"prefersBorder": False}})]
    target = resolve_resource(str(uri))
    if target is None:
        raise ValueError(f"Unknown resource: {uri}")
    tool, args = target
    out = await _in_thread(call_tool_for, _connection(), tool, args)
    return [ReadResourceContents(content=json.dumps(out, default=str, ensure_ascii=False), mime_type="application/json")]
