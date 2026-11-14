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

from marvin.services.ui_links import entry_edit_url, entry_review_link

from ..entity_resolve import resolve_entity_id
from ..operations.base import INVOCATION_SOURCES, ROLE_EDITOR
from .base import ToolContext, register_tool

# Agent-bound but not MCP-projected (MarvinMCP already has marvin_compose_entry via the endpoint).
_COMPOSE_SOURCES = tuple(s for s in INVOCATION_SOURCES if s != "mcp")


# What a draft tool's result says happened, in words an agent can pass on. An agent once told a user its staged
# (awaiting approval) changes were "Updated"; the plain sentence leaves it nothing to guess from `outcome`.
SAVED_MESSAGE = "Saved as an inbox draft: nothing is published."
UPDATED_MESSAGE = "Updated."
STAGED_MESSAGE = "Proposed, waiting for your approval: nothing has changed yet."
_OUTCOME_MESSAGES = {"applied": UPDATED_MESSAGE, "staged": STAGED_MESSAGE, "unchanged": "Nothing to change: the entry already says that."}


def _with_message(result: dict) -> dict:
    """The result of a change to an existing entry, with `message` saying in words what its `outcome` means."""
    message = _OUTCOME_MESSAGES.get(result.get("outcome"))
    return {**result, "message": message} if message else result


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
                "description": "optional existing asset ids to attach. ORDER MATTERS: the first becomes the hero, and only the first 4 are sent to the model as vision input — put the most important images first. Name each picture in the brief by its asset `name`, and add no facts the user did not give.",  # noqa: E501
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
    return json.dumps(_with_message(result))


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


def _draft_fields(entry_type, fields):
    """The fields a new draft is saved with. A new Playbook never carries ``replaces``: only propose_playbook_change sets it,
    and a stray one turns the draft into a change of a Playbook that may not be live (publishing it is then refused)."""
    from marvin.services.playbooks import PLAYBOOK_TYPE
    from marvin.services.playbooks.proposals import REPLACES_KEY

    if getattr(entry_type, "slug", None) == PLAYBOOK_TYPE and isinstance(fields, dict):
        return {k: v for k, v in fields.items() if k != REPLACES_KEY}
    return fields


def _picture(ctx: ToolContext, entry_type, asset_ids: list, fields: dict):
    """The picture a new entry is made for: the first of `assets`, else the first asset field (in the type's order) with a
    value. The Assets row and the field it came from (None when from `assets`), or (None, None)."""
    from marvin.db.models.platform.assets import Assets
    from marvin.services.entries.templates import ASSET_FIELD_TYPES

    found = [(asset_ids[0], None)] if asset_ids else []
    for f in (entry_type.schema_json or {}).get("fields", []):
        if isinstance(f, dict) and f.get("type") in ASSET_FIELD_TYPES and (value := fields.get(f.get("key"))):
            found.append((value[0] if isinstance(value, list) and value else value, f.get("key")))
    for ref, key in found:
        aid = resolve_entity_id(ctx.session, ctx.group_id, "asset", str(ref))
        asset = ctx.session.get(Assets, aid) if isinstance(aid, _uuid.UUID) else None
        if asset is not None and asset.group_id == ctx.group_id:
            return asset, key
    return None, None


@register_tool(
    name="create_draft",
    description=(
        "Save a NEW inbox draft with content already written: what the user gave word for word, or (for an assistant "
        "connected over MCP) what you wrote yourself. When the user asks Marvin to write or draft something, use "
        "compose_entry instead: it applies the workspace's voice and the type's recipe. Before "
        "writing, call get_entry_type for the type's fields (keys, types, required ones, choices) and list_tags; "
        "search_content or find_entries shows how the workspace writes and what to link. Only the type's own fields are "
        "accepted: an unknown key or a value of the wrong type is refused with the reason, so fix it and call again. "
        "Don't add descriptions, summaries or facts the user did not give or ask for. An entry made "
        "for a picture takes its title from the asset's `name` (list_assets / get_asset); leave `title` out and it does. "
        "For entries made from pictures, prefer the type's `template` when it has one (list_templates lists them): one "
        "call per picture, and what you pass explicitly wins over the template's values. "
        "Nothing is published. The result's reviewLink is a finished markdown link — give it to the user verbatim, and "
        "mention any `warnings` (what would still block publishing)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entry_type": {"type": "string", "description": "entry type slug or id"},
            **_DRAFT_PROPS,
            "title": {"type": "string", "description": "leave out with a picture: its name becomes the title"},
            "assets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "existing asset ids or slugs to attach, in order: the first becomes the hero (import_asset brings in new ones)",
            },
            "template": {
                "type": "string",
                "description": "a template of the entry type (slug, from list_templates): makes the entry for the first picture with it",
            },
        },
        "required": ["entry_type"],
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
    svc = _draft_service(ctx)
    fields = _draft_fields(et, args.get("fields"))
    try:
        known = svc._known_fields(et, fields)  # an unknown key is refused (naming the field it meant) before anything else
    except ValueError as e:
        return json.dumps({"error": str(e)})
    picture, from_field = _picture(ctx, et, asset_ids, known)
    if template := str(args.get("template") or "").strip():
        return json.dumps(_draft_from_template(ctx, svc, et, template, picture, from_field, known, args, more=len(asset_ids) > 1))
    title = str(args.get("title") or "").strip() or (picture.name if picture is not None else "")
    if not title:
        return json.dumps({"error": "title is required (or give a picture: its name becomes the title)"})
    try:
        result = svc.save_draft(
            entry_type=et, title=title, fields=fields, summary=args.get("summary"),
            tags=args.get("tags"), resources=args.get("resources"), asset_ids=asset_ids,
        )  # fmt: skip
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({**result, "message": SAVED_MESSAGE})


def _draft_from_template(ctx: ToolContext, svc, et, slug: str, picture, from_field, fields: dict, args: dict, *, more: bool) -> dict:
    """create_draft with a template: the entry for one picture, made by the template service (the same one the editor's
    "From template" uses), with what the caller gave explicitly winning over the template's values. A picture that already
    has an entry of this type is refused: that entry is changed with update_draft, never a second one made."""
    from marvin.services.entries import templates

    try:
        template = templates.template_of(et, slug)  # on the row we have, so a missing one names the ones there are
        if picture is None:
            return {"error": f"template '{slug}' makes an entry for a picture: give one in `assets` (list_assets lists them)"}
        overrides = {
            "title": str(args.get("title") or "").strip() or None,
            "summary": args.get("summary"),
            # The template puts the picture's id in its field itself; the caller's reference to it (maybe a slug) is not kept.
            "fields": {k: v for k, v in fields.items() if not (k == from_field and k == template.asset_field)},
        }
        plan = templates.plan_from_assets(ctx.session, ctx.group_id, str(et.id), template.slug, [str(picture.id)], overrides=overrides)
        row = plan.rows[0]
        if row.entry_id is not None:
            return {"error": f"that picture already has entry '{row.title}' ({row.entry_id}): use update_draft to change it"}
        if row.action != "create":
            return {"error": f"that picture can't be used: {row.note or row.error}"}
        if row.error:
            return {"error": f"the entry can't be made: {row.error}"}
        done = templates.execute(ctx.session, ctx.group_id, plan, actor_id=getattr(ctx.user, "id", None))
    except templates.TemplateError as e:
        return {"error": str(e)}
    entry_id = done["entry_ids"][0]
    tags = [str(t).strip() for t in (args.get("tags") or []) if str(t).strip()]
    if tags:  # the caller's tags, beside the template's
        svc.repos.entries.apply_fields(_uuid.UUID(entry_id), {"tags": tags})
    attached = svc._attach_existing_resources(_uuid.UUID(entry_id), args.get("resources") or [])
    ctx.session.commit()
    made = done["rows"][0]
    kind = {"inbox": "an inbox draft", "draft": "a draft", "needs_review": "a draft that needs review"}.get(template.status, "a draft")
    result = {
        "entryId": entry_id,
        "status": template.status,
        "title": made["title"],
        "template": template.slug,
        "tags": [*made["tags"], *(t for t in tags if t not in made["tags"])],
        "resources": attached,
        "warnings": svc._draft_warnings(_uuid.UUID(entry_id), et),
        "editUrl": entry_edit_url(entry_id),
        "reviewLink": entry_review_link(entry_id),
        "message": f"Saved as {kind} from template '{template.name}': nothing is published.",
    }
    if more:
        result["note"] = "only the first picture was used: call create_draft once per picture"
    return result


@register_tool(
    name="propose_playbook_change",
    description=(
        "Propose a change to a PUBLISHED Playbook: saves a separate inbox draft that names the Playbook it would replace, "
        "for an admin to compare and publish (publishing it updates that Playbook; until then nothing changes). Pass only "
        "what should differ; the rest is copied from the live one. Use it when you notice a better procedure or a correction "
        "people keep making. For a brand-new Playbook use create_draft with entry_type 'playbook'. "
        "The result's reviewLink is a finished markdown link — give it to the user verbatim."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "playbook": {"type": "string", "description": "the published Playbook's name"},
            "description": {"type": "string", "description": "the new one-line description"},
            "body": {"type": "string", "description": "the new full instructions (markdown)"},
            "license": {"type": "string"},
            "compatibility": {"type": "string"},
            "allowed_tools": {"type": "string", "description": "space-separated tool names"},
            "manual_only": {"type": "boolean"},
            "reason": {"type": "string", "description": "why: what you noticed, for the reviewer"},
        },
        "required": ["playbook"],
    },
    min_role=ROLE_EDITOR,
    read_only=False,
)
def propose_playbook_change(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.playbooks import CHANGE_KEYS, CHANGE_SUFFIX, REPLACES_KEY, ensure_playbook_type, published_playbook
    from marvin.services.playbooks.system import system_playbook

    name = str(args.get("playbook") or "").strip().lower()
    live = published_playbook(ctx.session, ctx.group_id, name)
    if live is None and (system := system_playbook(name)) is not None:
        return json.dumps(
            {
                "error": (
                    f"'{name}' is a system Playbook ({system.label}) and is read-only: "
                    "an admin copies it (Playbooks > System > Copy) and changes the copy."
                )
            }
        )
    if live is None:
        return json.dumps({"error": f"'{name}' is not a published Playbook (list_playbooks lists them). For a new one use create_draft."})
    row = ctx.session.get(Entries, _uuid.UUID(live.id))
    data = {k: v for k, v in (row.data_json or {}).items() if k in CHANGE_KEYS}
    changes = {k: args[k] for k in CHANGE_KEYS if k in args and args[k] != data.get(k)}
    if not changes:
        return json.dumps({"error": "nothing differs from the published Playbook: pass the description, body or other field you would change"})
    taken = {s for (s,) in ctx.session.query(Entries.slug).filter(Entries.group_id == ctx.group_id, Entries.slug.like(f"{name}{CHANGE_SUFFIX}%"))}
    title = f"{name}{CHANGE_SUFFIX}"
    for n in range(2, 1000):
        if title not in taken:
            break
        title = f"{name}{CHANGE_SUFFIX}-{n}"
    et = ctx.session.get(EntryTypes, ensure_playbook_type(ctx.session, ctx.group_id))
    try:
        result = _draft_service(ctx).save_draft(
            entry_type=et, title=title, summary=str(args.get("reason") or "").strip() or None,
            fields={**data, **changes, "name": title, REPLACES_KEY: name},
        )  # fmt: skip
    except ValueError as e:
        return json.dumps({"error": str(e)})
    # The review link opens the Playbooks page, which says what publishing replaces and shows the diff; the entry editor has neither.
    from marvin.services.ui_links import ui_link

    link = ui_link(f"/workspace/settings/ai-playbooks/{result['entryId']}")
    result = {**result, "editUrl": link, "reviewLink": f"[Review the proposed change]({link})"}
    note = f"Nothing changed yet: an admin publishes this draft to update '{name}'; it replaces that Playbook in place."
    return json.dumps({**result, "replaces": name, "note": note})


@register_tool(
    name="update_draft",
    description=(
        "Change some fields of an inbox, draft or needs-review entry to exact values (what the user gave, or what an "
        "assistant connected over MCP wrote itself): only what you pass changes. To improve or rewrite from an "
        "instruction ('tighten the intro'), use revise_entry. Field keys and types from "
        "get_entry_type; tags and resources are added. Published or approved entries are refused. Under the workspace's "
        "approval policy the change is applied, or staged for a person to approve (outcome 'staged'): then nothing has "
        "changed yet, so tell the user it is proposed and waiting for their approval, never that it was updated (the "
        "result's `message` says which). Don't add values or facts the user did not give or ask for. The result's "
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
    return json.dumps(_with_message(result))
