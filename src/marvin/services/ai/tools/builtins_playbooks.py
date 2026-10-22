"""Playbook tools (category `playbooks_read`): the catalog and the full text of published Playbooks.

A Playbook is guidance, not a capability: loading one returns text and grants nothing, so both tools are read-only and
open to any role. What may be seen is decided in `services/playbooks` (published only, this workspace only, plus the system
Playbooks its workspace gets), so the agent, MarvinMCP and the remote MCP server — which all project the registry — answer the same
way. A caller with no agent (MCP, the invoke route) is a person driving the tools: it may list and load a manual-only Playbook by name.
"""

from __future__ import annotations

import json

from marvin.services.ai.operations.base import ROLE_VIEWER
from marvin.services.playbooks import (
    LIST_TOOL,
    LOAD_TOOL,
    READ_FILE_TOOL,
    PlaybookScope,
    SystemFile,
    manual_only_refusal,
    published_playbook,
    published_playbook_file,
    published_playbook_files,
    published_playbooks,
)

from .base import ToolContext, register_tool
from .builtins_attachments import cut_text


def _scope(ctx: ToolContext) -> PlaybookScope:
    return ctx.playbooks or PlaybookScope(direct=True)  # no agent: a person drives the tools


@register_tool(
    name=LIST_TOOL,
    description=(
        "List this workspace's published Playbooks (its own, and the system Playbooks Marvin and its plugins give every "
        "workspace): written procedures for particular tasks, each with a name and a one-line description of when to use it. "
        "Call it before drafting, revising or reviewing something, then load_playbook "
        "the one that matches the task. (Marvin's own agents also get this list in their instructions.)"
    ),
    input_schema={"type": "object", "properties": {}},
    min_role=ROLE_VIEWER,
    read_only=True,
)
def list_playbooks(ctx: ToolContext, _args: dict) -> str:
    found = published_playbooks(ctx.session, ctx.group_id, _scope(ctx))
    return json.dumps({"playbooks": [_listed(p) for p in found]})


def _listed(p) -> dict:
    return {
        "name": p.name,
        "description": p.description,
        **({"system": p.label} if p.is_system else {}),
        **({"manualOnly": True} if p.manual_only else {}),
    }


@register_tool(
    name=LOAD_TOOL,
    description=(
        "Load a published Playbook by name and get its full instructions. Call it when the request matches a Playbook's "
        "description, before you start the task, then follow it using the tools you already have. A Playbook grants no "
        "extra tools or permissions. Its reference files, if any, come back as a list of paths, not their contents."
    ),
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The Playbook's name, as listed (e.g. 'bench-note-voice')."}},
        "required": ["name"],
    },
    min_role=ROLE_VIEWER,
    read_only=True,
)
def load_playbook(ctx: ToolContext, args: dict) -> str:
    name = str(args.get("name") or "").strip()
    scope = _scope(ctx)
    found = published_playbook(ctx.session, ctx.group_id, name, scope)
    if found is None:
        available = [p.name for p in published_playbooks(ctx.session, ctx.group_id, scope)]
        if why := manual_only_refusal(ctx.session, ctx.group_id, name, scope):
            return json.dumps({"error": why, "available": available})
        return json.dumps({"error": f"No published Playbook named '{name}'.", "available": available})
    files = published_playbook_files(ctx.session, ctx.group_id, name, scope) or []
    return json.dumps(
        {
            "id": found.id,
            "name": found.name,
            **({"source": found.label, "version": found.version, "hash": found.hash} if found.is_system else {}),
            "description": found.description,
            "body": found.body,
            "files": [{"path": f.path, "mimeType": f.mime_type, "size": f.size} for f in files],
            "note": "Follow these instructions with the tools you already have; they do not grant any others."
            + (f" The files are not loaded: read one with {READ_FILE_TOOL} only when the instructions point to it." if files else ""),
        }
    )


@register_tool(
    name=READ_FILE_TOOL,
    description=(
        "Read one reference file of a published Playbook, by the path listed when you loaded it (e.g. 'references/tone.md'). "
        "Read a file only when the Playbook's instructions point to it. Long files are cut at `max_chars`; the result says when."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "playbook": {"type": "string", "description": "The Playbook's name."},
            "path": {"type": "string", "description": "The file's path as listed by load_playbook."},
            "max_chars": {"type": "integer", "description": "Most characters to return (default and maximum 20000)."},
        },
        "required": ["playbook", "path"],
    },
    min_role=ROLE_VIEWER,
    read_only=True,
)
def read_playbook_file(ctx: ToolContext, args: dict) -> str:
    from .builtins_attachments import read_asset_text

    name, path = str(args.get("playbook") or "").strip(), str(args.get("path") or "").strip()
    scope = _scope(ctx)
    asset = published_playbook_file(ctx.session, ctx.group_id, name, path, scope)
    if asset is None:
        files = published_playbook_files(ctx.session, ctx.group_id, name, scope)
        if files is None:
            if why := manual_only_refusal(ctx.session, ctx.group_id, name, scope):
                return json.dumps({"error": why})
            return json.dumps(
                {
                    "error": f"No published Playbook named '{name}'.",
                    "available": [p.name for p in published_playbooks(ctx.session, ctx.group_id, scope)],
                }
            )
        return json.dumps({"error": f"The Playbook '{name}' has no file '{path}'.", "files": [f.path for f in files]})
    if isinstance(asset, SystemFile):
        out = cut_text(asset.text, args.get("max_chars"), {"name": asset.name})
    else:
        out = read_asset_text(asset, args.get("max_chars"))
    return json.dumps({"playbook": name, "path": path, **out})
