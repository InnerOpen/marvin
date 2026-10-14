"""Workflow authoring for agents: the guide they write from, and the checks a drafted workflow gets.

Asked to build a workflow, an agent once said it couldn't, then wrote invented JSON (`steps`,
`type: find_entries`, `for_each`, `{{steps[...]}}`) that nothing in Marvin reads. A model writes the
real format only from facts, so this module hands it the facts — read from the code that runs a
workflow, never written out as prose that can drift:

- the definition's shape, triggers and steps from the Pydantic definition models (their fields and
  docstrings), entry ops and what each sends from the entry executor, condition operators and fields
  from the matcher and validation, the target query keys from the shared entry query, the template
  namespaces from the engine, the events from the event catalog;
- this workspace's own references: collections, entry types and their fields, integrations and their
  actions, webhooks, other workflows, the AI operations and internal jobs a step may run.

``draft_issues`` is what a drafted definition must pass: the REST write path's own structural gate
(``validation.structural_issues``), then two checks only an agent's draft gets, because a model
inventing a key or a name is the failure they catch — unknown keys (the API keeps them for forward
compatibility, and nothing reads them) and references to things this workspace doesn't have.
"""

from __future__ import annotations

import json
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# What the guide offers (`section=`, one or several); without one it gives the index.
SECTIONS = ("shape", "triggers", "events", "target", "conditions", "actions", "media", "templates", "workspace", "examples", "editor")

# The index: one line per section — what it holds, and when a request needs it. The guide is read like a vault: the
# index first (small, always), then only the sections the request calls for (several in one call), so a model's
# context carries what it uses and the guide can grow with the catalogue.
SECTION_GUIDE: dict[str, str] = {
    "shape": "the definition's object (trigger, target, conditions, actions, on_failure) and the drafting rules · always",
    "triggers": (
        "each trigger type's fields (event, manual with inputs, schedule, chained, on_error, incoming_webhook, mcp) · once the trigger type is chosen"
    ),
    "events": "the events a workflow can start on, by heading, and what each carries · when the trigger is an event",
    "target": ("running on a query of entries, assets or resources instead of the trigger's item: the query keys · when it acts on many items"),
    "conditions": "condition operators and the fields they read · when the run should be filtered, or a step has a `when`",
    "actions": "every step kind with its fields, the entry ops, and reading a step's result · always, for the kinds used",
    "media": (
        "the media step's ops (resize, crop, render, OCR, PDF, zip, watermark…) and the render templates · when images or documents are involved"
    ),
    "templates": (
        "the ${…} names a step can read (event, entry, asset, steps, input, member…) and how they resolve · when a step reads the "
        "entry or an earlier step"
    ),
    "workspace": (
        "this workspace's entry types with their fields, collections, integrations and their actions, webhooks, workflows, AI operations · always"
    ),
    "examples": "the Library recipes this workspace can run; recipe=<id> shows one in full · first, to start from one instead of writing",
    "editor": "the workflow editor's own labels for each part · when telling a person what to click",
}
INDEX_BUDGET = 4_000  # characters: the index is read on every request
SECTION_BUDGET = 16_000

# Workspace lists are capped, like workspace_overview's structure: the guide must stay one tool result.
REF_LIMIT = 50


# ── Reading the definition models ────────────────────────────────────────────
def _type_name(annotation: Any) -> str:
    """A field's annotation as a model reads it: `"string"`, `"object"`, `"a | b"` for a Literal."""
    from pydantic import BaseModel

    origin = typing.get_origin(annotation)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "object"
    if origin is typing.Literal:
        return " | ".join(str(a) for a in typing.get_args(annotation))
    if origin in (typing.Union, types.UnionType):
        return " | ".join(dict.fromkeys(_type_name(a) for a in typing.get_args(annotation) if a is not type(None)))
    if origin is dict or annotation is dict:
        return "object"
    if origin is list or annotation is list:
        return "list"
    if typing.get_origin(annotation) is typing.Annotated:
        return _type_name(typing.get_args(annotation)[0])
    names = {str: "string", bool: "boolean", int: "integer", float: "number"}
    if annotation in names:
        return names[annotation]
    return "any" if annotation is Any else getattr(annotation, "__name__", str(annotation))


def _fields(model, *, skip: tuple[str, ...] = ()) -> dict:
    """{"required": {name: type}, "optional": {name: type}} for a definition model."""
    required: dict[str, str] = {}
    optional: dict[str, str] = {}
    for name, f in model.model_fields.items():
        key = f.alias or name
        if key in skip:
            continue
        (required if f.is_required() else optional)[key] = _type_name(f.annotation)
    return {"required": required, "optional": optional}


def _doc(model) -> str:
    return " ".join((model.__doc__ or "").split())


# ── This workspace's references ──────────────────────────────────────────────
@dataclass
class WorkspaceRefs:
    """What a definition in this workspace can name — the guide lists it, `draft_issues` checks against it."""

    collections: list[dict] = field(default_factory=list)
    entry_types: list[dict] = field(default_factory=list)
    integrations: list[dict] = field(default_factory=list)
    outgoing_webhooks: list[dict] = field(default_factory=list)
    incoming_webhooks: list[dict] = field(default_factory=list)
    workflows: list[dict] = field(default_factory=list)
    # None: AI operations can't run from a workflow here (AI off, or the automation source disabled).
    operations: list[dict] | None = None
    handlers: list[dict] = field(default_factory=list)
    grade_presets: list[str] = field(default_factory=list)  # a media step's `grade` presets: built-in + the workspace's


def automation_operations(session, group_id) -> list | None:
    """The AI operations a workflow step may run here, or None when none can (AI off, or the workspace's
    invocation policy disables the `automation` source) — what the builder offers and a draft is checked against."""
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.operations import list_operations

    from .runner import AUTOMATION_SOURCE

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    if not (settings and getattr(settings, "enabled", False)):
        return None
    policy = settings.invocation_sources
    if isinstance(policy, dict) and policy.get(AUTOMATION_SOURCE, True) is False:
        return None
    from marvin.services.ai.operations.custom import CUSTOM

    # Plus the step's own prompt (`op: "custom"`): not a registered operation, but a workflow may run one.
    return [op for op in list_operations() if AUTOMATION_SOURCE in op.invocation_sources] + [CUSTOM]


def _integration_actions(provider_slug: str) -> list[dict] | None:
    """A provider's actions a workflow can run — an approval-gated one (`requires_approval`) only after an approval
    step; None when the provider isn't installed."""
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return None
    from marvin.services.integrations import get_provider

    try:
        provider = get_provider(provider_slug)
    except KeyError:
        return None
    out = []
    for a in getattr(provider, "actions", ()) or ():
        schema = a.input_schema or {}
        props = schema.get("properties") or {}
        out.append(
            {
                "action": a.key,
                "label": a.label,
                "description": a.description,
                "args": {k: (v.get("type") if isinstance(v, dict) else None) or "any" for k, v in props.items()},
                "required": list(schema.get("required") or []),
                "capability": getattr(a, "capability", None),
                **({"requires_approval": True} if getattr(a, "requires_approval", False) else {}),
            }
        )
    return out


def _integration_capabilities(provider_slug: str) -> list[str] | None:
    """What a provider can do for a step that names a capability (`notify`…); None when it isn't installed."""
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return None
    from marvin.services.integrations import get_provider
    from marvin.services.integrations.alert_routing import capabilities_of

    try:
        return sorted(capabilities_of(get_provider(provider_slug)))
    except KeyError:
        return None


def _integration_guide(provider_slug: str) -> str | None:
    """The how-to the provider's plugin ships (services/integrations/guides.py), or None."""
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return None
    from marvin.services.integrations.guides import guide_for

    guide = guide_for(provider_slug)
    return guide.markdown if guide else None


DATE_FIELD_TYPES = ("date", "datetime")


def _entry_type_ref(t) -> dict:
    fields = [f for f in (t.schema_json or {}).get("fields", []) if isinstance(f, dict)]
    return {
        "slug": t.slug,
        "name": t.name,
        "fields": [f.get("key") for f in fields],
        "date_fields": [f.get("key") for f in fields if f.get("type") in DATE_FIELD_TYPES],
    }


def workspace_refs(session, group_id) -> WorkspaceRefs:
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.scheduled_tasks.handlers import TaskHandlerRegistry

    from .actions.handler import AUTOMATION_ALLOWED_HANDLERS

    refs = WorkspaceRefs()
    refs.collections = [
        {"slug": c.slug, "name": c.name}
        for c in session.query(Collections).filter(Collections.group_id == group_id).order_by(Collections.name).limit(REF_LIMIT)
    ]
    types_q = session.query(EntryTypes).filter((EntryTypes.group_id == group_id) | (EntryTypes.group_id.is_(None))).order_by(EntryTypes.name)
    # A workspace's own type and a built-in one can share a slug: the workspace's is the one a step names (as at run
    # time), so it is listed once.
    by_slug: dict[str, Any] = {}
    for t in types_q.all():
        if t.slug not in by_slug or (by_slug[t.slug].group_id is None and t.group_id is not None):
            by_slug[t.slug] = t
    refs.entry_types = [_entry_type_ref(t) for t in sorted(by_slug.values(), key=lambda t: (t.name or "").lower())[:REF_LIMIT]]
    for row in session.query(IntegrationModel).filter_by(group_id=group_id).order_by(IntegrationModel.name).limit(REF_LIMIT):
        refs.integrations.append(
            {
                "slug": row.slug,
                "name": row.name,
                "provider": row.provider,
                "enabled": bool(row.enabled),
                "actions": _integration_actions(row.provider),
                "capabilities": _integration_capabilities(row.provider),
                "has_guide": _integration_guide(row.provider) is not None,
            }
        )
    # Ids and names only: an outgoing webhook's URL can carry a credential.
    refs.outgoing_webhooks = [
        {"id": str(w.id), "name": w.name or "(unnamed)"}
        for w in session.query(GroupWebhooksModel).filter_by(group_id=group_id).order_by(GroupWebhooksModel.name).limit(REF_LIMIT)
    ]
    refs.incoming_webhooks = [
        {"slug": w.slug, "name": w.name, "enabled": bool(w.enabled)}
        for w in session.query(WorkspaceIncomingWebhookModel)
        .filter_by(group_id=group_id)
        .order_by(WorkspaceIncomingWebhookModel.name)
        .limit(REF_LIMIT)
    ]
    refs.workflows = [
        {"id": str(a.id), "slug": a.slug, "name": a.name, "enabled": bool(a.enabled)}
        for a in session.query(WorkspaceAutomationModel).filter_by(group_id=group_id).order_by(WorkspaceAutomationModel.name).limit(REF_LIMIT)
    ]
    ops = automation_operations(session, group_id)
    if ops is not None:
        refs.operations = [{"op": op.slug, "name": op.name, "description": op.description, "entity_types": list(op.entity_types)} for op in ops]
    info = {i["task_type"]: i for i in TaskHandlerRegistry.get_task_type_info()}
    refs.handlers = [{"task": t, "description": (info.get(t) or {}).get("description", "")} for t in sorted(AUTOMATION_ALLOWED_HANDLERS)]
    from marvin.services.ai.media.enrichment import grade_presets

    refs.grade_presets = sorted(grade_presets(session, group_id))
    return refs


# ── The guide ────────────────────────────────────────────────────────────────
def _shape() -> dict:
    from marvin.schemas.group.automation_definition import AutomationDefinition

    return {
        "workflow": "draft_workflow(name, definition): the definition is the object below; a workflow is created disabled.",
        "definition": _fields(AutomationDefinition),
        "notes": [
            "Keys are snake_case exactly as listed; any other key is rejected (there is no `steps`, `for_each` or `type` on a step).",
            "Steps go in `actions`, run in order, each with a `kind`. To act on many entries, give a `target` query: the steps run once per match.",
            "`on_failure` steps run when a step fails, with `${error.*}`. `integration_errors`: policy (default) | fail.",
            "Use the trigger the user asked for; when they named none, `manual`. Never add a schedule or event they didn't ask "
            "for. A trash step over a target is always drafted `manual` (draft_workflow refuses anything else). A recipe keeps its trigger.",
        ],
    }


def _triggers() -> dict:
    from marvin.schemas.group.automation_definition import TRIGGER_MODELS
    from marvin.schemas.platform.scheduled_tasks import ScheduledTaskCreate

    from .validation import condition_field_catalog

    out: dict[str, Any] = {kind: {"description": _doc(model), **_fields(model, skip=("type",))} for kind, model in TRIGGER_MODELS.items()}
    out["schedule"]["schedule_types"] = list(typing.get_args(ScheduledTaskCreate.model_fields["schedule_type"].annotation))
    for kind, fields in condition_field_catalog().items():
        if kind in out:
            out[kind]["condition_fields"] = [f["field"] for f in fields]
    return out


def _events() -> dict:
    from marvin.services.events.event_catalog import CATALOG_BY_TYPE, offered_emittable, trigger_groups

    groups: dict[str, Any] = {g: {e: CATALOG_BY_TYPE[e].description for e in names} for g, names in trigger_groups().items()}
    return {
        "triggerable": groups,
        "emittable": offered_emittable(),
        "note": "An event trigger names one triggerable event. describe_event gives an event's `event.*` fields.",
    }


def _target() -> dict:
    from marvin.schemas.platform.entries import ENTRY_STATUSES
    from marvin.services.entries.query import SPEC_KEY_NOTES
    from marvin.services.item_query import KEY_NOTES

    from .selector import MAX_TARGET_ENTITIES

    return {
        "entity": "entry (default) | asset | resource — each match runs the steps as that entity (`${entry.*}`, `${asset.*}`, `${resource.*}`)",
        "query": SPEC_KEY_NOTES,
        "statuses": sorted(ENTRY_STATUSES),
        "example": {"entity": "entry", "query": {"entry_type": "recipe", "status": "published"}},
        "asset": {"query": KEY_NOTES["asset"], "example": {"entity": "asset", "query": {"asset_type": "image", "unattached": True}}},
        "resource": {
            "query": KEY_NOTES["resource"],
            "example": {"entity": "resource", "query": {"resource_type": "supplier", "tags": ["wool"]}},
        },
        "limit": f"at most {MAX_TARGET_ENTITIES} matches per run",
        "note": (
            "A query is a flat object of that entity's keys (`query` above is the entry's; no `where` operators on assets or resources, "
            "and no publish status: an asset or resource is in the Trash — `trashed: true` — or it is not). Values may be templates. "
            "Items in the Trash match only a query that asks for them."
        ),
    }


def _conditions() -> dict:
    from .matcher import _OPS
    from .validation import condition_field_catalog

    out: dict[str, Any] = {
        "form": "a list (all must hold) of {field, op, value}; groups: {all: [...]}, {any: [...]}, {not: {...}}",
        "ops": list(_OPS),
        "field": "a bare dotted path (no $), e.g. entry.status, entry.data.<field>, event.payload.<key>",
        "note": "Conditions are checked before any step runs, so steps.* / previous.* aren't available in them.",
    }
    out["fields"] = condition_field_catalog()  # per trigger type, each field with what it means
    return out


def _actions() -> dict:
    from marvin.schemas.group.automation_definition import ACTION_MODELS

    from .actions.entry import ENTRY_OPS, OP_SENDS, REVIEW_STATUS
    from .engine import MAX_ACTIONS

    kinds = {kind: {"description": _doc(model), **_fields(model, skip=("kind",))} for kind, model in ACTION_MODELS.items()}
    entry_ops: dict[str, Any] = {}
    for op, sends in OP_SENDS.items():
        status = ENTRY_OPS.get(op) or (REVIEW_STATUS if op == "request_review" else None)
        entry_ops[op] = {"sets_status": status, "sends": list(sends)}
    entry_ops_note = (
        "`unpublish` and `restore` set status draft (there is no op to set any other status); add/remove_from_collection "
        "need collection_slug; set_metadata needs `metadata`, set_data needs `data` (the type's fields); request_review takes `reason`; "
        "attach_asset needs `asset` (an id or slug) and takes `role`."
    )
    return {
        "kinds": kinds,
        "entry_ops": entry_ops,
        "entry_ops_note": entry_ops_note + CREATE_NOTE,
        "asset_resource_ops": _item_ops(),
        "max_steps": MAX_ACTIONS,
        "step_id": "Give a step an `id` to read its output later as ${steps.<id>.output.<key>}; any step takes `when` (run only if).",
        "when": WHEN_NOTE,
        "media": "section=media has the media step in full: each op's rules and the render templates.",
        "collect": COLLECT_NOTE,
        "fetch": FETCH_NOTE,
    }


def _render_templates() -> dict:
    """The built-in render templates as the guide lists them: what each is, its size, its fields and pictures (* required)."""
    from marvin.services.ai.media.render import templates

    star = lambda specs: [k + ("*" if v.get("required") else "") for k, v in specs.items()]  # noqa: E731
    return {
        slug: {"about": t["description"], "size": f"{t['width']}x{t['height']}", "fields": star(t["fields"]), "images": star(t["images"])}
        for slug, t in templates().items()
    }


COLLECT_NOTE = (
    "collect is many → one: it runs a query (entity entry|asset|resource, query = a target's keys; dates may be relative, "
    "published_after: -7d) under any trigger and outputs rows (each like ${entry.*} / ${asset.*}, plus extra `fields` "
    "paths such as data.body), count, total and text — a ready list for a custom AI step's prompt "
    "(${steps.<id>.output.text}). A render step's images may take ${steps.<id>.output.rows} whole (the grid and "
    "moodboard templates). Use `when` on count (gt 0) to skip an empty digest."
)
FETCH_NOTE = (
    "fetch reads the web for a step: with a target over published entries, links: ${entry.data.body} then a `when` on "
    "steps.<id>.output.broken_count (gt 0) → notify with ${steps.<id>.output.text} is a broken-link patrol (not request_review: "
    "it unpublishes a live entry). Broken = "
    "no answer, 404, 410 or 5xx (401/403/429 are a server refusing robots). url: a resource's page "
    '(${resource.url}) → `when` on output.ok; find: "sold out" (any case) → output.found lists what is there. Public addresses only.'
)
MEDIA_NOTE = (
    "A media step works on one image (jpeg, png, webp): source is an asset id or slug (default ${asset.id}), "
    "${entry.image} for the entry's main picture (any of the workspace's own asset URLs works), "
    "${steps.<id>.output.asset.id} to chain, or role:<role> for the run's entry's image in that role. resize (width/height, "
    "fit inside|cover; never upscales), crop (aspect like 4:5; focus subject asks a vision model once per image per run, else centre — output "
    "focus_used), convert (format), grade (preset) save a NEW asset and output asset {id, slug, url, width, height}, "
    "reused: the same op on the same image is made once, the original is never changed, and the new asset records "
    "derived_from + the workflow (no asset_uploaded is sent; asset.derived_from tells derivatives apart). format/quality "
    "re-encode any of them. inspect outputs width, height, orientation, aspect, sharpness (Laplacian variance: blurry is "
    "low, roughly under 100); palette outputs colors ['#rrggbb']. attach_as links the new asset to the run's entry in that "
    "role (attach_to: another entry, e.g. one the run created); tags tags the new asset. render fills a template — "
    "template: one of card, quote, poster, "
    "trading-card, meme, side-by-side, comic-4, newspaper (section=media lists each one's fields and images), or html: your "
    "own HTML/CSS with {{ fields.<name> }} / {{ images.<name> }} — with fields (text) and images (name → an asset, as source "
    "takes), at width × height (the template's own size by default), and saves the screenshot as a new asset; no network or "
    "script runs in it. An integration action with an image.* capability (openai_images.generate) "
    "keeps its pictures the same way — output images: [{asset}] — and takes attach_as and tags too. extract_text: a PDF's "
    "own text is free, a scanned page or a picture costs one vision call (ocr: never skips them); outputs text with "
    "[page N] marks and pages. pages outputs asset (first) and assets. find_sensitive outputs regions + count; redact "
    "takes boxes: ${steps.<id>.output.regions} (count 0 makes nothing). zip takes files: a gather step's rows. "
    "render with format pdf prints (the guide template does by default). watermark: text and/or logo; position a corner, "
    "center or tiled; opacity; size (% of the width)."
)
CREATE_NOTE = (
    " create makes a new entry: entry_type (slug), title, optional data (the type's fields) and metadata, status draft|inbox "
    "(publish with a following publish step on ${steps.<id>.output.entry_id}); output entry_id/slug; once per event."
)
WHEN_NOTE = (
    "Any step may carry `when` (conditions, same shape and ops as `conditions`): it runs only if they hold at that point, "
    "reading ${steps.<id>.output.*} / previous.* too; false records it as skipped, not failed, and its output reads as None. "
    'Two steps with opposite `when`s (one wrapped in {"not": …}) are an if/else.'
)


def _item_ops() -> dict:
    """What entry steps can do to assets and resources."""
    from .actions.entry import ITEM_OP_SENDS

    items = sorted({op for _kind, op in ITEM_OP_SENDS})
    return {
        "ops": items,
        "acts_on": (
            "the current item: each match of an asset/resource target, or the triggering asset/resource (asset_* / resource_* events) "
            "— entity_type may then be left out; or one named by entity_slug / entity_id (with entity_type asset | resource)"
        ),
        "sends": {f"{kind} {op}": list(sends) for (kind, op), sends in ITEM_OP_SENDS.items()},
        "note": (
            "entity_query finds entries only. Every other entry op acts on entries; an operation step on an asset/resource "
            "needs an AI operation that supports it."
        ),
    }


def _templates() -> dict:
    from .engine import TEMPLATE_NAMESPACES

    return {
        "syntax": [
            '"${path}" as a whole value keeps the value\'s type; inside text ("Hi ${entry.title}") it is stringified.',
            '"$path" (whole value, no braces) also works. {{...}}, steps[...] and other forms are NOT templates.',
            '"${path|url}" URL-encodes the value: for a share link\'s text or a query string.',
        ],
        "namespaces": TEMPLATE_NAMESPACES,
        "where": "step fields (input, args, body, metadata, data, entity_slug, collection_slug, reason…), target.query values, condition values",
    }


def _workspace(refs: WorkspaceRefs) -> dict:
    integrations = [{**i, "actions": i["actions"] if i["actions"] is not None else "provider not installed"} for i in refs.integrations]
    # A connected integration's own how-to (its plugin's guide).
    with_guide = sorted({i["provider"] for i in refs.integrations if i.get("enabled") and i.get("has_guide")})
    guides: dict[str, Any] = {"integration_guides": {p: _integration_guide(p) for p in with_guide}} if with_guide else {}
    return {
        **guides,
        "collections": [c["slug"] for c in refs.collections],  # what a step names (collection_slug takes a slug or a name)
        "entry_types": refs.entry_types,
        "integrations": integrations,
        "outgoing_webhooks": refs.outgoing_webhooks,
        "incoming_webhooks": refs.incoming_webhooks,
        "workflows": [{"slug": w["slug"], "name": w["name"], "enabled": w["enabled"]} for w in refs.workflows],
        "operations": (
            "AI operations can't run from workflows here (AI is off, or its automation source is disabled)"
            if refs.operations is None
            else refs.operations
        ),
        "handlers": refs.handlers,
    }


# Worked definitions are the Workflow Library's recipes (services/automation/recipes): one store for the
# guide, the Library and draft_workflow(recipe=…). Only recipes that validate and run today, and whose
# prerequisites this workspace meets, are offered; tests/test_workflow_library.py drafts every one.
GIST = 110  # characters of a recipe's outcome in the examples list


def _gist(text: str) -> str:
    """A recipe's outcome cut to its first clause, or to a word boundary near GIST characters, marked "…" when cut."""
    if len(text) <= GIST:
        return text
    head = text[:GIST]
    for stop in ("; ", " — ", ", "):
        if (at := head.find(stop)) > GIST // 2:
            return head[:at] + "…"
    return head.rsplit(" ", 1)[0] + "…"


def _examples(refs: WorkspaceRefs, recipe: str | None) -> dict:
    from . import recipes

    offered = recipes.offered(refs)
    if recipe:
        item = next((r for r in offered if r["id"] == recipe), None)
        if item is None:
            known = recipes.entry(recipe) if recipe in {r["id"] for r in recipes.entries()} else None
            why = "; ".join(recipes.missing_prerequisites(known, refs)) or f"its status is {known['status']}" if known else "no such recipe"
            return {"error": f"recipe “{recipe}” isn't available here ({why}).", "available": [r["id"] for r in offered]}
        return {"note": _EXAMPLES_NOTE, recipe: recipes.example(item)}
    # Id and the outcome's gist only (the id is the title, slugged): the list must stay under the size budget as the
    # library grows; recipe=<id> has the rest.
    return {
        "note": _EXAMPLES_NOTE + " Call again with recipe=<id> for one recipe's full definition and setup variables.",
        "recipes": [{"recipe": r["id"], "outcome": _gist(r["outcome"])} for r in offered],
    }


_EXAMPLES_NOTE = (
    "Library recipes this workspace can run. `{{name}}` is a setup placeholder (its type and meaning in setup_variables): "
    "fill it from the workspace's own names, or pass recipe + vars to draft_workflow. `${…}` is a run-time template — leave it."
)


_EDITOR_LABELS = Path(__file__).with_name("editor_labels.json")


def _editor() -> dict:
    """The workflow editor's own words for each part (a copy of frontend/src/lib/workflowLabels.json, kept equal by
    tests/test_editor_labels.py): guided steps name what the person sees ("Run on a query", "Set fields"), not
    the definition's keys."""
    labels = json.loads(_EDITOR_LABELS.read_text())
    labels.pop("_comment", None)
    return {"note": "Use these labels when telling a person what to click; the keys are the definition's names.", **labels}


def authoring_guide(session, group_id, section: str | None = None, recipe: str | None = None) -> dict:
    """The guide: without ``section``, the index (what each section holds and when to read it, plus this workspace's
    entry type slugs and how many recipes it can run); with ``section`` — one name, or several comma-separated — those
    sections in full. ``recipe`` names one Library recipe to show in full (the examples section). Raises ValueError
    for an unknown section."""
    if recipe and not section:
        section = "examples"
    if not section:
        return _index(session, group_id)
    want = tuple(dict.fromkeys(s.strip() for s in section.split(",") if s.strip()))
    if unknown := [s for s in want if s not in SECTIONS]:
        raise ValueError(f"unknown section '{', '.join(unknown)}' — one or more of: {', '.join(SECTIONS)} (comma-separated)")
    out: dict[str, Any] = {}
    refs: WorkspaceRefs | None = None
    if "shape" in want:
        out["shape"] = _shape()
    if "triggers" in want:
        out["triggers"] = _triggers()
    if "events" in want:
        out["events"] = _events()
    if "target" in want:
        out["target"] = _target()
    if "conditions" in want:
        out["conditions"] = _conditions()
    if "actions" in want:
        out["actions"] = _actions()
    if "media" in want:
        out["media"] = {"note": MEDIA_NOTE, "render_templates": _render_templates()}
    if "templates" in want:
        out["templates"] = _templates()
    if "workspace" in want or "examples" in want:
        refs = workspace_refs(session, group_id)
    if "workspace" in want:
        assert refs is not None
        out["workspace"] = _workspace(refs)
    if "examples" in want:
        assert refs is not None
        out["examples"] = _examples(refs, recipe)
    if "editor" in want:
        out["editor"] = _editor()
    return out


def _first_sentence(text: str) -> str:
    head = text.split(". ", 1)[0]
    return head if head.endswith(".") else head + "."


def _index(session, group_id) -> dict:
    """The first read: what a workflow is and how it is drafted, where each kind of detail lives, and the little
    about this workspace that decides where to look next."""
    from marvin.db.models.platform.collections import Collections
    from marvin.schemas.group.automation_definition import ACTION_MODELS

    from . import recipes

    refs = workspace_refs(session, group_id)
    return {
        "step_kinds": {kind: _first_sentence(_doc(model)) for kind, model in ACTION_MODELS.items()},
        "start": (
            "A workflow (automation) is a trigger, optional conditions and up to ten steps; draft one with draft_workflow(name, "
            "definition) — it is created switched off, for the person to enable. Read the sections this request needs, several in "
            "one call (section=shape,actions,workspace,templates), then draft; a Library recipe may already do it (section=examples, "
            "then draft_workflow with recipe + vars)."
        ),
        "sections": dict(SECTION_GUIDE),
        "workspace": {
            "entry_types": [t["slug"] for t in refs.entry_types],
            "collections": session.query(Collections).filter(Collections.group_id == group_id).count(),
            "integrations": [i["slug"] for i in refs.integrations if i.get("enabled")],
            "recipes_ready": len(recipes.offered(refs)),
            "detail": "section=workspace",
        },
    }


def guide_size(guide: dict) -> int:
    return len(json.dumps(guide))


# ── Reading what a model passed ──────────────────────────────────────────────
@dataclass
class ParsedWorkflow:
    """A workflow as an agent passed it, normalised like the editor's JSON view (frontend/src/lib/workflowJson.ts)."""

    definition: dict | None = None
    name: str | None = None
    slug: str | None = None
    ignored: list[str] = field(default_factory=list)
    error: str | None = None


ACCEPTED_SHAPES = 'Pass a definition like {"trigger": {…}, "actions": […]} (or a whole workflow like {"name": "…", "definition": {…}}).'
_DOCUMENT_KEYS = ("name", "slug", "definition")
# Keys that belong to the workflow, not its definition, when a bare definition carries them by mistake.
_WORKFLOW_KEYS_IN_DEFINITION = ("name", "slug", "enabled")


def parse_workflow(value: Any) -> ParsedWorkflow:
    """Accept a bare definition or a whole workflow document ({name, slug?, definition}), as the editor's
    JSON view does; `enabled` is never taken from it. A JSON string is read too (models sometimes send one)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as e:
            return ParsedWorkflow(error=f"definition is not valid JSON: {e}")
    if not isinstance(value, dict):
        return ParsedWorkflow(error=f"definition must be an object. {ACCEPTED_SHAPES}")
    if "definition" in value:
        if not isinstance(value["definition"], dict):
            return ParsedWorkflow(error='"definition" must be an object.')
        definition = dict(value["definition"])
        ignored = [k for k in value if k not in _DOCUMENT_KEYS]
    else:
        if "trigger" not in value and "actions" not in value:
            return ParsedWorkflow(error=f'This is not a workflow definition: it has no "trigger" or "actions". {ACCEPTED_SHAPES}')
        definition = {k: v for k, v in value.items() if k not in _WORKFLOW_KEYS_IN_DEFINITION}
        ignored = ["enabled"] if "enabled" in value else []
    if "enabled" in definition:  # a document's definition carrying it: still the workflow's, never taken
        definition.pop("enabled")
        ignored.append("definition.enabled")
    for key in ("name", "slug"):
        if value.get(key) is not None and not isinstance(value[key], str):
            return ParsedWorkflow(error=f'"{key}" must be a string.')
    name = value["name"].strip() if isinstance(value.get("name"), str) and value["name"].strip() else None
    slug = value["slug"].strip() if isinstance(value.get("slug"), str) and value["slug"].strip() else None
    return ParsedWorkflow(definition=definition, name=name, slug=slug, ignored=ignored)


# ── What a drafted definition must pass ──────────────────────────────────────
def _templated(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("$")


def _close(value: str, options: list[str], limit: int = 12) -> str:
    from .validation import close_options

    return close_options(value, options, limit)


class _Issues(list):
    """ERROR issues in the shape every definition check returns: {level, message, where, path}."""

    def add(self, path: str, where: str, message: str) -> None:
        self.append({"level": "error", "message": message, "where": where, "path": path})


def _values(value: Any) -> list[str]:
    """The literal strings of a one-or-many query value; templates are left to run time."""
    return [v for v in (value if isinstance(value, list) else [value]) if isinstance(v, str) and not _templated(v)]


def reference_issues(session, group_id, definition: dict, refs: WorkspaceRefs | None = None) -> list[dict]:
    """Names the definition uses that this workspace (or Marvin) doesn't have — an event no trigger can
    listen to, an operation, job, integration, webhook, collection or entry type that isn't there. Each
    is an ERROR issue ({level, message, where, path}); a template value (`$…`) is left to run time.
    Run on a structurally valid definition."""
    from .validation import subject_of

    refs = refs or workspace_refs(session, group_id)
    issues = _Issues()
    _trigger_issues(definition.get("trigger") or {}, refs, issues)
    if isinstance(definition.get("target"), dict):
        _target_issues(definition["target"], refs, issues)
    _condition_issues(definition.get("conditions"), "conditions", issues)
    subject = subject_of(definition)
    for list_key, where in (("actions", "action"), ("on_failure", "on_failure")):
        after_approval = False  # an approval-gated integration action is accepted after an approval step only
        for i, step in enumerate(definition.get(list_key) or []):
            if isinstance(step, dict):
                gated = after_approval and list_key == "actions"
                _step_issues(step, f"{list_key}[{i}]", where, refs, issues, subject, after_approval=gated)
                for j, inner in enumerate(step.get("steps") or [] if step.get("kind") == "repeat" else []):
                    if isinstance(inner, dict):
                        _step_issues(inner, f"{list_key}[{i}].steps[{j}]", where, refs, issues, subject, after_approval=gated)
                after_approval = after_approval or step.get("kind") == "approval"
    return issues


def _trigger_issues(trig: dict, refs: WorkspaceRefs, issues: _Issues) -> None:
    from marvin.services.events.event_catalog import TRIGGERABLE_EVENT_TYPES, canonical_event_type

    ttype = trig.get("type", "event")
    event = trig.get("event")
    if ttype == "event" and isinstance(event, str) and canonical_event_type(event) not in TRIGGERABLE_EVENT_TYPES:
        issues.add(
            "trigger.event",
            "trigger",
            f"“{event}” is not an event a workflow can trigger on. Events: {_close(event, sorted(TRIGGERABLE_EVENT_TYPES))}.",
        )
    ref = trig.get("automation")
    if ttype in ("chained", "on_error") and ref and ref != "any" and not any(ref in (w["slug"], w["id"]) for w in refs.workflows):
        issues.add("trigger.automation", "trigger", f"No workflow “{ref}” here. Workflows: {_close(ref, [w['slug'] for w in refs.workflows])}.")
    hook = trig.get("webhook")
    if ttype == "incoming_webhook" and hook and hook != "any" and hook not in {w["slug"] for w in refs.incoming_webhooks}:
        known = _close(hook, [w["slug"] for w in refs.incoming_webhooks])
        issues.add("trigger.webhook", "trigger", f"No incoming webhook “{hook}” here. Incoming webhooks: {known}.")
    if ttype == "schedule":
        from marvin.schemas.platform.scheduled_tasks import ScheduledTaskCreate

        allowed = typing.get_args(ScheduledTaskCreate.model_fields["schedule_type"].annotation)
        if trig.get("schedule_type", "interval") not in allowed:
            issues.add("trigger.schedule_type", "trigger", f"schedule_type must be one of {', '.join(allowed)}.")


def _target_issues(target: dict, refs: WorkspaceRefs, issues: _Issues) -> None:
    """Names a target's query uses that this workspace doesn't have (its keys are checked by validation.query_issues)."""
    from marvin.schemas.platform.entries import ENTRY_STATUSES
    from marvin.services.item_query import ASSET_TYPES

    entity = target.get("entity") or "entry"
    type_slugs = [t["slug"] for t in refs.entry_types]
    spellings = {s.replace("-", "_") for s in type_slugs}
    collections = {c["slug"] for c in refs.collections} | {c["name"] for c in refs.collections}
    for key, value in (target.get("query") or {}).items():
        path = f"target.query.{key}"
        if key in ("asset_type", "asset_types") and entity == "asset":
            for v in _values(value):
                if v not in ASSET_TYPES:
                    issues.add(path, "target", f"“{v}” is not an asset type ({', '.join(ASSET_TYPES)}).")
        elif entity != "entry":
            if key in ("collection", "collections"):
                for v in _values(value):
                    if v not in collections:
                        issues.add(path, "target", f"No collection “{v}” here. Collections: {_close(v, [c['slug'] for c in refs.collections])}.")
        elif key in ("entry_type", "entry_types"):
            for v in _values(value):
                if v.replace("-", "_") not in spellings:
                    issues.add(path, "target", f"No entry type “{v}” here. Entry types: {_close(v, type_slugs)}.")
        elif key in ("collection", "collections"):
            for v in _values(value):
                if v not in collections:
                    issues.add(path, "target", f"No collection “{v}” here. Collections: {_close(v, [c['slug'] for c in refs.collections])}.")
        elif key in ("status", "statuses"):
            for v in _values(value):
                if v not in ENTRY_STATUSES:
                    issues.add(path, "target", f"“{v}” is not a publish status ({', '.join(sorted(ENTRY_STATUSES))}).")


def _condition_issues(node: Any, path: str, issues: _Issues) -> None:
    from .matcher import _OPS

    if isinstance(node, list):
        for i, c in enumerate(node):
            _condition_issues(c, f"{path}[{i}]", issues)
    elif isinstance(node, dict):
        for group in ("all", "any", "not"):
            if group in node:
                _condition_issues(node[group], f"{path}.{group}", issues)
        if "field" in node and node.get("op", "eq") not in _OPS:
            issues.add(f"{path}.op", "condition", f"Unknown condition operator “{node.get('op')}”. Operators: {', '.join(_OPS)}.")


def _step_issues(
    step: dict, path: str, where: str, refs: WorkspaceRefs, issues: _Issues, subject: str = "entry", *, after_approval: bool = False
) -> None:
    def bad(key: str, message: str) -> None:
        issues.add(f"{path}.{key}" if key else path, where, message)

    kind = step.get("kind")
    if kind == "operation":
        ops = {o["op"]: o for o in refs.operations or []}
        if refs.operations is None:
            bad("", "AI operations can't run from workflows in this workspace (AI is off, or its automation source is disabled).")
        elif step.get("op") not in ops:
            bad("op", f"No AI operation “{step.get('op')}”. Operations: {_close(str(step.get('op')), list(ops))}.")
        else:
            # The step runs on its entity_type, else on what the run acts on (an asset/resource target's rows or
            # event's item, else an entry) — the operation has to support that kind.
            etype = step.get("entity_type") or subject
            supported = ops[step["op"]]["entity_types"]
            if supported and etype not in supported:
                runs_on = f"this workflow runs on {etype}s" if not step.get("entity_type") else f"entity_type is {etype}"
                bad("op" if not step.get("entity_type") else "entity_type", f"“{step['op']}” runs on {' / '.join(supported)}, but {runs_on}.")
    elif kind == "entry":
        _entry_step_issues(step, refs, bad)
    elif kind == "emit_event":
        from marvin.services.events.event_catalog import EMITTABLE_EVENT_TYPES, canonical_event_type

        event = step.get("event")
        if isinstance(event, str) and canonical_event_type(event) not in EMITTABLE_EVENT_TYPES:
            bad("event", f"“{event}” can't be sent by a workflow. Emittable: {_close(event, sorted(EMITTABLE_EVENT_TYPES))}.")
    elif kind == "handler":
        if step.get("task") not in {h["task"] for h in refs.handlers}:
            bad("task", f"“{step.get('task')}” is not a job a workflow may run. Jobs: {', '.join(h['task'] for h in refs.handlers)}.")
    elif kind == "webhook":
        wid = step.get("webhook_id")
        if not wid and not step.get("url"):
            bad("webhook_id", "A webhook step needs webhook_id (one of the workspace's outgoing webhooks) or url.")
        elif wid and not _templated(wid) and wid not in {w["id"] for w in refs.outgoing_webhooks}:
            names = "; ".join(f"{w['id']} ({w['name']})" for w in refs.outgoing_webhooks[:10]) or "(none in this workspace)"
            bad("webhook_id", f"No outgoing webhook “{wid}” here. Outgoing webhooks: {names}.")
    elif kind == "integration":
        slug, key, capability = step.get("integration"), step.get("action"), step.get("capability")
        row = next((i for i in refs.integrations if i["slug"] == slug), None)
        if row is None:
            bad("integration", f"No integration “{slug}” here. Integrations: {_close(str(slug), [i['slug'] for i in refs.integrations])}.")
        elif not key and capability:
            if row.get("capabilities") is not None and capability not in row["capabilities"]:
                able = ", ".join(i["slug"] for i in refs.integrations if capability in (i.get("capabilities") or [])) or "(none here)"
                bad("capability", f"“{slug}” can't {capability}. Integrations that can: {able}.")
        elif row["actions"] is not None and key not in {a["action"] for a in row["actions"]}:
            actions = ", ".join(a["action"] for a in row["actions"]) or "(none)"
            bad("action", f"“{slug}” has no action “{key}” a workflow can run. Actions: {actions}.")
        elif row["actions"] is not None and not after_approval and any(a["action"] == key and a.get("requires_approval") for a in row["actions"]):
            bad("action", f"“{slug}.{key}” needs a person's approval: put an Approval step before it (it runs once approved).")
        elif (step.get("attach_as") or step.get("tags") or step.get("source")) and row["actions"] is not None:
            declared = next((a for a in row["actions"] if a["action"] == key), None)
            if declared is not None and not str(declared.get("capability") or "").startswith("image."):
                field_name = next(f for f in ("source", "attach_as", "tags") if step.get(f))
                bad(field_name, f"{field_name} goes with an action that makes images; “{slug}.{key}” doesn't.")
    elif kind == "media":
        _media_step_issues(step, refs, bad)
    elif kind == "fetch":
        _fetch_step_issues(step, bad)


def _fetch_step_issues(step: dict, bad) -> None:
    url = step.get("url")
    if isinstance(url, str) and not _templated(url) and urlparse(url.strip()).scheme not in ("http", "https"):
        bad("url", f"“{url}” isn't a web address: it needs http:// or https://.")


def _media_step_issues(step: dict, refs: WorkspaceRefs, bad) -> None:
    if step.get("op") == "render" and isinstance(step.get("template"), str) and not _templated(step["template"]):
        _render_step_issues(step, bad)
    preset = step.get("preset")
    if step.get("op") == "grade" and isinstance(preset, str) and not _templated(preset) and preset not in refs.grade_presets:
        bad("preset", f"No grade preset “{preset}”. Presets: {', '.join(refs.grade_presets)}.")


def _render_step_issues(step: dict, bad) -> None:
    """A render step naming a built-in template: it exists, and the step fills its required text and pictures (a
    template value is checked when it runs) and nothing it doesn't have."""
    from marvin.services.ai.media.render import templates

    manifest = templates().get(step["template"])
    if manifest is None:
        bad("template", f"No render template “{step['template']}”. Templates: {', '.join(sorted(templates()))}.")
        return
    for key, given in (("fields", step.get("fields") or {}), ("images", step.get("images") or {})):
        known = manifest[key]
        if unknown := sorted(set(given) - set(known)):
            bad(key, f"The {manifest['label']} template has no {key[:-1]} {', '.join(unknown)}. Its {key}: {', '.join(known)}.")
        if missing := [k for k, spec in known.items() if spec.get("required") and given.get(k) in (None, "")]:
            bad(key, f"The {manifest['label']} template needs {', '.join(missing)} in `{key}`.")


def _entry_step_issues(step: dict, refs: WorkspaceRefs, bad) -> None:
    op = step.get("op")
    if op in ("add_to_collection", "remove_from_collection"):
        ref = step.get("collection_slug")
        known = {c["slug"] for c in refs.collections} | {c["name"] for c in refs.collections}
        if not ref and not step.get("collection_id"):
            bad("collection_slug", f"“{op}” needs collection_slug.")
        elif isinstance(ref, str) and not _templated(ref) and ref not in known:
            bad("collection_slug", f"No collection “{ref}” here. Collections: {_close(ref, [c['slug'] for c in refs.collections])}.")
    if op == "attach_asset" and not step.get("asset"):
        bad(
            "asset",
            "attach_asset needs `asset`: the asset's id or slug — a template to a step's picture works "
            "(${steps.<id>.output.images.0.asset.id}).",
        )
    if op == "set_metadata" and not step.get("metadata"):
        bad("metadata", "set_metadata needs `metadata`: the keys to merge into the entry's metadata.")
    if op == "set_data" and not step.get("data"):
        bad("data", "set_data needs `data`: the entry type's field keys and their new values.")
    if op == "create":
        ref = step.get("entry_type")
        known = {t["slug"]: t for t in refs.entry_types}
        if isinstance(ref, str) and not _templated(ref):
            if ref not in known:
                bad("entry_type", f"No entry type “{ref}” here. Entry types: {_close(ref, list(known))}.")
            else:
                unknown = sorted(k for k in (step.get("data") or {}) if k not in known[ref]["fields"])
                if unknown:
                    bad("data", f"“{ref}” has no field {', '.join(unknown)}. Its fields: {', '.join(known[ref]['fields']) or '(none)'}.")


def draft_issues(session, group_id, definition: dict) -> list[dict]:
    """Everything that stops an agent's draft: the REST write path's structural gate first (exactly the
    function `POST /api/automations` calls) with the query shapes and item-target steps a run can't read
    (advisory on the REST path), then unknown keys and unknown references. Empty: draftable."""
    from .validation import entry_link_issues, item_target_issues, query_issues, structural_issues, unknown_key_issues

    issues = structural_issues(definition) + query_issues(definition) + item_target_issues(definition) + entry_link_issues(definition)
    issues += _trash_sweep_issues(definition)
    if issues:
        return issues
    return unknown_key_issues(definition) + reference_issues(session, group_id, definition)


def _trash_sweep_issues(definition: dict) -> list[dict]:
    """An agent never drafts a trash sweep that runs on its own (validation.unattended_trash_issues, a warning in the
    editor): nobody would be asked before every match is trashed, while the agent's own trash tools always ask first.
    It saves the sweep manual; making it scheduled or event-driven is the user's call, in the editor."""
    from .validation import unattended_trash_issues

    if not unattended_trash_issues(definition):
        return []
    return [
        {
            "level": "error",
            "where": "trigger",
            "path": "trigger.type",
            "message": (
                'A Move to Trash step over a target can\'t be drafted to run on its own: set the trigger to {"type": "manual"} '
                "and call again — even when the user asked for a schedule or an event. Then tell them it is manual, and that "
                "only they can switch the trigger in the workflow editor, after a dry run."
            ),
        }
    ]
