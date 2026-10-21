"""Built-in AUTHORING tools — compose / revise entries through the shared AuthoringService.

The SAME brain the ``/ai/compose-entry`` and ``/ai/revise-entry`` endpoints use, so "create such-
and-such entry" or "determine tags for this entry" from chat does exactly what the buttons do:
grounded on the existing tag vocabulary + RAG-relevant resources/assets, reusing rather than
duplicating. Gated at EDITOR, read_only=False: revise works on any entry, which only an EDITOR may
change, and every write tool takes the same floor. Both create/mutate DRAFTS for human review.

``create_draft`` / ``update_draft`` save fields the CALLER wrote (an assistant connected over MCP, or Marvin's own
agent for an exact edit) through the same service with no model of Marvin's: no AI provider or budget needed.

``compose_entry`` withholds the ``mcp`` source so it doesn't collide with MarvinMCP's existing
hand-wired ``marvin_compose_entry`` (that path already projects the same endpoint); ``revise_entry``
is new, so it projects to MCP normally.
"""

import json
import uuid as _uuid

from ..entity_resolve import resolve_entity_id
from ..operations.base import INVOCATION_SOURCES, ROLE_EDITOR
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


def _entry_type(ctx: ToolContext, ref: str):
    """The workspace's (or a built-in) entry type by slug or id, or None."""
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.playbooks import PLAYBOOK_TYPE, ensure_playbook_type

    et = (
        ctx.session.query(EntryTypes)
        .filter(EntryTypes.slug == ref)
        .filter((EntryTypes.group_id == ctx.group_id) | (EntryTypes.group_id.is_(None)))
        .first()
    )
    if not et and ref == PLAYBOOK_TYPE:  # the Playbook type is made when the first one is written: an agent's draft is that
        et = ctx.session.get(EntryTypes, ensure_playbook_type(ctx.session, ctx.group_id))
    if not et:
        try:
            et = ctx.session.get(EntryTypes, _uuid.UUID(ref))
        except (ValueError, TypeError):
            et = None
    return et if et is not None and et.group_id in (None, ctx.group_id) else None


@register_tool(
    name="compose_entry",
    uses_ai=True,
    description=(
        "Create a NEW draft entry of a given type from a brief: Marvin's authoring writes it in the workspace's voice, "
        "following the type's recipe (image roles, linked resources), grounded on existing tags and related content, "
        "which it REUSES (no duplicates). Use this when the user asks you to write, draft or come up with something; "
        "use create_draft only to save content the user gave word for word. Call it straight away with a good brief: it "
        "looks up the type's fields, tags and related entries, resources and images itself, so don't research those "
        "first (only to put specific facts in the brief). Lands as an inbox draft "
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
    min_role=ROLE_EDITOR,
    read_only=False,
    sources=_COMPOSE_SOURCES,
)
def compose_entry(ctx: ToolContext, args: dict) -> str:
    svc, err = _service(ctx)
    if err:
        return err
    ref = str(args.get("entry_type") or "").strip()
    et = _entry_type(ctx, ref)
    if et is None:
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
        register=ctx.tone_register,
    )
    return json.dumps(result)


@register_tool(
    name="revise_entry",
    uses_ai=True,
    description=(
        "Revise an EXISTING entry in place from an instruction — never recreates it. E.g. 'determine "
        "the tags and attach any relevant resources', or 'tighten the summary'. For an exact value the user gave "
        "('set the price to 450'), use update_draft instead. Reuses existing "
        "tags/resources. Identify the entry by slug or id. Not for deleting, removing or clearing out entries — "
        "use trash_entries (or archive_entries to retire one). The result's reviewLink is a finished markdown "
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
    min_role=ROLE_EDITOR,
    read_only=False,
)
def revise_entry(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.platform.entries import Entries
    from marvin.services.playbooks import agent_change_refusal

    eid = resolve_entity_id(ctx.session, ctx.group_id, "entry", args.get("entry"))
    entry = ctx.session.get(Entries, eid) if isinstance(eid, _uuid.UUID) else None
    if not entry or entry.group_id != ctx.group_id:
        return json.dumps({"error": f"entry '{args.get('entry')}' not found in this workspace"})
    if refusal := agent_change_refusal(ctx.session, entry):
        return json.dumps({"error": refusal})
    svc, err = _service(ctx)
    if err:
        return err
    result = svc.revise(
        entry=entry,
        instruction=str(args.get("instruction") or ""),
        source="agent",
        parent_execution_id=ctx.execution_id,
        register=ctx.tone_register,
    )
    return json.dumps(result)


# ── drafts the caller writes itself (no model of Marvin's) ───────────────────

_DRAFT_PROPS = {
    "title": {"type": "string"},
    "summary": {"type": "string", "description": "one or two sentences"},
    "fields": {"type": "object", "description": "the entry type's own fields {field_key: value}; keys and value types from get_entry_type"},
    "tags": {"type": "array", "items": {"type": "string"}, "description": "tag names; existing ones are reused (list_tags), new ones created"},
    "resources": {
        "type": "array",
        "items": {"type": "string"},
        "description": "existing resources to link (slug, id or name); unknown ones are skipped",
    },
}


def _draft_service(ctx: ToolContext):
    from marvin.services.ai.authoring import AuthoringService

    return AuthoringService(ctx.session, ctx.group_id, ctx.user, provider=None, model=None)


@register_tool(
    name="create_draft",
    description=(
        "Save a NEW inbox draft with content already written: what the user gave word for word, or (for an assistant "
        "connected over MCP) what you wrote yourself. When the user asks Marvin to write or draft something, use "
        "compose_entry instead: it applies the workspace's voice and the type's recipe. Before "
        "writing, call get_entry_type for the type's fields (keys, types, required ones, choices) and list_tags; "
        "search_content or find_entries shows how the workspace writes and what to link. Only the type's own fields are "
        "accepted: an unknown key or a value of the wrong type is refused with the reason, so fix it and call again. "
        "Nothing is published. The result's reviewLink is a finished markdown link — give it to the user verbatim, and "
        "mention any `warnings` (what would still block publishing)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entry_type": {"type": "string", "description": "entry type slug or id"},
            **_DRAFT_PROPS,
            "assets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "existing asset ids or slugs to attach, in order: the first becomes the hero (import_asset brings in new ones)",
            },
        },
        "required": ["entry_type", "title"],
    },
    min_role=ROLE_EDITOR,
    read_only=False,
)
def create_draft(ctx: ToolContext, args: dict) -> str:
    ref = str(args.get("entry_type") or "").strip()
    et = _entry_type(ctx, ref)
    if et is None:
        return json.dumps({"error": f"entry type '{ref}' not found in this workspace (list_entry_types lists them)"})
    asset_ids = []
    for a in args.get("assets") or []:
        aid = resolve_entity_id(ctx.session, ctx.group_id, "asset", a)
        if not isinstance(aid, _uuid.UUID):
            return json.dumps({"error": f"asset '{a}' not found in this workspace (list_assets, or import_asset to add it)"})
        asset_ids.append(str(aid))
    try:
        result = _draft_service(ctx).save_draft(
            entry_type=et, title=str(args.get("title") or ""), fields=args.get("fields"), summary=args.get("summary"),
            tags=args.get("tags"), resources=args.get("resources"), asset_ids=asset_ids,
        )  # fmt: skip
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps(result)


@register_tool(
    name="update_draft",
    description=(
        "Change some fields of an inbox, draft or needs-review entry to exact values (what the user gave, or what an "
        "assistant connected over MCP wrote itself): only what you pass changes. To improve or rewrite from an "
        "instruction ('tighten the intro'), use revise_entry. Field keys and types from "
        "get_entry_type; tags and resources are added. Published or approved entries are refused. Under the workspace's "
        "approval policy the change is applied, or staged for a person to approve (outcome 'staged'). The result's "
        "reviewLink is a finished markdown link — give it to the user verbatim."
    ),
    input_schema={
        "type": "object",
        "properties": {"entry": {"type": "string", "description": "the entry by slug or id"}, **_DRAFT_PROPS},
        "required": ["entry"],
    },
    min_role=ROLE_EDITOR,
    read_only=False,
)
def update_draft(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.platform.entries import Entries
    from marvin.services.playbooks import agent_change_refusal

    eid = resolve_entity_id(ctx.session, ctx.group_id, "entry", args.get("entry"))
    entry = ctx.session.get(Entries, eid) if isinstance(eid, _uuid.UUID) else None
    if not entry or entry.group_id != ctx.group_id:
        return json.dumps({"error": f"entry '{args.get('entry')}' not found in this workspace"})
    if refusal := agent_change_refusal(ctx.session, entry):
        return json.dumps({"error": refusal})
    try:
        result = _draft_service(ctx).update_draft(
            entry=entry, title=args.get("title"), summary=args.get("summary"), fields=args.get("fields"), tags=args.get("tags"),
            resources=args.get("resources"),
        )  # fmt: skip
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps(result)
