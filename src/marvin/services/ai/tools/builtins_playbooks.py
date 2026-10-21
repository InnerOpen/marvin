"""Playbook tools (category `playbooks_read`): the catalog and the full text of published Playbooks.

A Playbook is guidance, not a capability: loading one returns text and grants nothing, so both tools are read-only and
open to any role. What may be seen is decided in `services/playbooks` (published only, this workspace only), so the
agent, MarvinMCP and the remote MCP server — which all project the registry — answer the same way.
"""

from __future__ import annotations

import json

from marvin.services.ai.operations.base import ROLE_VIEWER
from marvin.services.playbooks import LIST_TOOL, LOAD_TOOL, published_playbook, published_playbooks

from .base import ToolContext, register_tool


@register_tool(
    name=LIST_TOOL,
    description=(
        "List this workspace's published Playbooks: written procedures for particular tasks, each with a name and a "
        "one-line description of when to use it. Use it to check what exists; the catalog in your instructions is the same list."
    ),
    input_schema={"type": "object", "properties": {}},
    min_role=ROLE_VIEWER,
    read_only=True,
)
def list_playbooks(ctx: ToolContext, _args: dict) -> str:
    found = published_playbooks(ctx.session, ctx.group_id)
    return json.dumps({"playbooks": [{"name": p.name, "description": p.description} for p in found]})


@register_tool(
    name=LOAD_TOOL,
    description=(
        "Load a published Playbook by name and get its full instructions. Call it when the request matches a Playbook's "
        "description, before you start the task, then follow it using the tools you already have. A Playbook grants no "
        "extra tools or permissions."
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
    found = published_playbook(ctx.session, ctx.group_id, name)
    if found is None:
        available = [p.name for p in published_playbooks(ctx.session, ctx.group_id)]
        return json.dumps({"error": f"No published Playbook named '{name}'.", "available": available})
    return json.dumps(
        {
            "id": found.id,
            "name": found.name,
            "description": found.description,
            "body": found.body,
            "note": "Follow these instructions with the tools you already have; they do not grant any others.",
        }
    )
