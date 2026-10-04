"""Built-in AUTHORING tools — compose / revise entries through the shared AuthoringService.

The SAME brain the ``/ai/compose-entry`` and ``/ai/revise-entry`` endpoints use, so "create such-
and-such entry" or "determine tags for this entry" from chat does exactly what the buttons do:
grounded on the existing tag vocabulary + RAG-relevant resources/assets, reusing rather than
duplicating. Gated at AUTHOR, read_only=False. Both create/mutate DRAFTS for human review.

``compose_entry`` withholds the ``mcp`` source so it doesn't collide with MarvinMCP's existing
hand-wired ``marvin_compose_entry`` (that path already projects the same endpoint); ``revise_entry``
is new, so it projects to MCP normally.
"""

import json
import uuid as _uuid

from ..entity_resolve import resolve_entity_id
from ..operations.base import INVOCATION_SOURCES, ROLE_AUTHOR
from .base import ToolContext, register_tool

# Agent-bound but not MCP-projected (MarvinMCP already has marvin_compose_entry via the endpoint).
_COMPOSE_SOURCES = tuple(s for s in INVOCATION_SOURCES if s != "mcp")


def _service(ctx: ToolContext):
    from marvin.services.ai.authoring import AuthoringService, default_authoring_model

    if ctx.provider is None:
        return None, json.dumps({"error": "authoring requires an AI provider (none configured for this workspace)"})
    model = default_authoring_model(ctx.session, ctx.group_id, ctx.provider)
    if not model:
        return None, json.dumps({"error": "no AI model configured for this workspace"})
    return AuthoringService(ctx.session, ctx.group_id, ctx.user, ctx.provider, model), None


@register_tool(
    name="compose_entry",
    description=(
        "Create a NEW draft entry of a given type from a brief. Grounds on the workspace's existing "
        "tags + relevant resources/assets and REUSES them (no duplicates). Lands as an inbox draft "
        "for review. To change an existing entry, use revise_entry instead of recreating it. When the new entry should "
        "link to other entries, put each one's `url` (from find_entries / get_entry) in the brief. The result's "
        "reviewLink is a finished markdown link — give it to the user verbatim; never build a URL yourself."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entry_type": {"type": "string", "description": "entry type slug or id"},
            "brief": {"type": "string", "description": "what the entry should be about"},
            "asset_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "optional existing asset ids to attach. ORDER MATTERS: the first becomes the hero, and only the first 4 are sent to the model as vision input — put the most important images first.",  # noqa: E501
            },
        },
        "required": ["entry_type", "brief"],
    },
    min_role=ROLE_AUTHOR,
    read_only=False,
    sources=_COMPOSE_SOURCES,
)
def compose_entry(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.platform.entry_types import EntryTypes

    svc, err = _service(ctx)
    if err:
        return err
    ref = str(args.get("entry_type") or "").strip()
    et = (
        ctx.session.query(EntryTypes)
        .filter(EntryTypes.slug == ref)
        .filter((EntryTypes.group_id == ctx.group_id) | (EntryTypes.group_id.is_(None)))
        .first()
    )
    if not et:
        try:
            et = ctx.session.get(EntryTypes, _uuid.UUID(ref))
        except (ValueError, TypeError):
            et = None
    if not et or et.group_id not in (None, ctx.group_id):
        return json.dumps({"error": f"entry type '{ref}' not found in this workspace"})

    asset_ids = args.get("asset_ids") or []
    aa = svc.recipe_asset_attachments(asset_ids, et) if asset_ids else None
    result = svc.compose(
        entry_type=et,
        brief=str(args.get("brief") or ""),
        asset_ids=asset_ids,
        asset_attachments=aa,
        source="agent",
        parent_execution_id=ctx.execution_id,
    )
    return json.dumps(result)


@register_tool(
    name="revise_entry",
    description=(
        "Revise an EXISTING entry in place from an instruction — never recreates it. E.g. 'determine "
        "the tags and attach any relevant resources', or 'tighten the summary'. Reuses existing "
        "tags/resources. Identify the entry by slug or id. The result's reviewLink is a finished markdown "
        "link — give it to the user verbatim; never build a URL yourself."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entry": {"type": "string", "description": "the entry by slug or id"},
            "instruction": {"type": "string", "description": "what to determine / change"},
        },
        "required": ["entry", "instruction"],
    },
    min_role=ROLE_AUTHOR,
    read_only=False,
)
def revise_entry(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.platform.entries import Entries

    svc, err = _service(ctx)
    if err:
        return err
    eid = resolve_entity_id(ctx.session, ctx.group_id, "entry", args.get("entry"))
    entry = ctx.session.get(Entries, eid) if isinstance(eid, _uuid.UUID) else None
    if not entry or entry.group_id != ctx.group_id:
        return json.dumps({"error": f"entry '{args.get('entry')}' not found in this workspace"})
    result = svc.revise(entry=entry, instruction=str(args.get("instruction") or ""), source="agent", parent_execution_id=ctx.execution_id)
    return json.dumps(result)
