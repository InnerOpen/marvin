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
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# What the guide offers (`section=`, one or several); without one it gives the index.
SECTIONS = (
    "shape",
    "triggers",
    "events",
    "target",
    "conditions",
    "actions",
    "media",
    "email",
    "records",
    "social",
    "templates",
    "workspace",
    "examples",
    "editor",
)

# The index: one line per section — what it holds, and when a request needs it. The guide is read like a vault: the
# index first (small, always), then only the sections the request calls for (several in one call), so a model's
# context carries what it uses and the guide can grow with the catalogue.
SECTION_GUIDE: dict[str, str] = {
    "shape": "the definition's object (trigger, target, conditions, actions, on_failure) and the drafting rules · always",
    "triggers": (
        "each trigger type's fields (event, manual with inputs, schedule, chained, on_error, incoming_webhook, mcp) · once the trigger type is chosen"
    ),
    "events": "the events a workflow can start on or send, by heading (custom ones too), and what each carries · when the trigger is an event",
    "target": ("running on a query of entries, assets or resources instead of the trigger's item: the query keys · when it acts on many items"),
    "conditions": "condition operators and the fields they read · when the run should be filtered, or a step has a `when`",
    "actions": "every step kind with its fields, the entry ops, and reading a step's result · always, for the kinds used",
    "media": (
        "the media step's ops (resize, crop, render, OCR, PDF, zip, watermark…) and the render templates · when images or documents are involved"
    ),
    "email": "the email step in full: who it may write to, sending once, links by role, what a dry run shows · when a step writes to a member",
    "records": "the metric, snapshot and schema_check steps in full · when counting, keeping versions or checking JSON",
    "social": "social.post and the engagement capabilities (comments, reply, like, hide, delete, repost, message) · when posting or answering",
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
INDEX_BUDGET = 4_200  # characters: the index is read on every request
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
    custom_events: list[dict] = field(default_factory=list)  # the workspace's own events: {event_type, description, fields}


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
    from marvin.services.integrations.alert_routing import needs_approval

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
                **({"requires_approval": True} if needs_approval(a) else {}),
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
    from marvin.services.events import custom_events

    refs.custom_events = [
        {
            "event_type": custom_events.event_type_of(e.name),
            "description": custom_events.catalog_entry(e).description,
            "fields": {f.key: f.type for f in e.fields},
        }
        for e in custom_events.read(session, group_id)
    ]
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


def _events(refs: WorkspaceRefs) -> dict:
    from marvin.services.events.event_catalog import (
        CATALOG_BY_TYPE,
        OPERATIONS,
        SOCIAL,
        offered_emittable,
        operational_fields,
        social_fields,
        trigger_groups,
        workflow_reads,
    )

    groups: dict[str, Any] = {g: {e: CATALOG_BY_TYPE[e].description for e in names} for g, names in trigger_groups().items()}
    out: dict[str, Any] = {
        "triggerable": groups,
        "emittable": offered_emittable(),
        "note": "An event trigger names one triggerable event. describe_event gives an event's `event.*` fields.",
    }
    if OPERATIONS in groups:
        out["operations"] = {
            "fields": {e: {k: f["type"] for k, f in operational_fields(e).items()} for e in groups[OPERATIONS]},
            "note": (
                "The Operations events report the platform failing or running short; a workflow reads their fields as ${event.<field>} "
                "(`event.<field>` in a condition). A workflow is never woken by a failure its own run caused (its webhook, its AI call, its "
                "integration step), so it can't loop; its own failures still reach people through Settings → Automation → Notifications, "
                "which needs no workflow. Scheduled tasks count only the workspace's own, not the platform's. A repeat while a repair task "
                "is open should make no second one: look it up first (a `collect` step on a metadata key) and `when` the create on none."
            ),
        }
    if SOCIAL in groups:
        out["social"] = {
            "fields": {e: {k: f["type"] for k, f in social_fields(e).items()} for e in groups[SOCIAL]},
            "note": (
                "social_comment_received: a new comment, reply or mention on a connected network that offers social.comments, once per "
                "item, from the Social engagement scheduled task's poll (it must be enabled; the engine's rehearsal setting doesn't "
                "matter). Never the account's own, nothing older than 7 days, and the first poll announces no backlog. A workflow reads "
                "${event.id}, .kind, .text, .author.handle, .author.name, .post_url, .url, .network, .integration (the connection's "
                "slug) and conditions key on them (event.kind eq mention, event.text contains refund). To answer, an integration "
                'step takes the slug as a template: {"kind": "integration", "integration": "${event.integration}", "capability": '
                '"social.reply", "args": {"comment_id": "${event.id}", "text": "…"}} after an Approval step; social.hide and '
                "social.like need no approval. Its own reply is the account's own item, so it never starts the workflow again."
            ),
        }
    out["form_submission_received"] = {  # its extra namespace, for a step that classifies or routes the submission
        **(reads := workflow_reads("form_submission_received")),
        "fields": list(reads["fields"]),
    }
    if refs.custom_events:
        # The workspace's own events: triggerable and emittable like the rest, their fields typed.
        types = [e["event_type"] for e in refs.custom_events]
        groups["Custom"] = {e["event_type"]: e["description"] for e in refs.custom_events}
        out["emittable"] = [*out["emittable"], *types]
        out["custom"] = {
            "events": {e["event_type"]: e["fields"] for e in refs.custom_events},
            "note": (
                "A custom event is this workspace's own (Settings → Automation → Custom events). An Emit event step sends one with "
                "`payload`: {field: value, …}, values may be templates (${entry.title}); a field is string, number, boolean or date, "
                "and a step may name only the fields listed. Workflows that start on it read `${event.payload.<field>}`."
            ),
        }
    return out


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
        "changed": "On entry_updated, `changed` / `changed_from` / `changed_to` read the diff: status, title, slug and the type's own fields "
        "as `data.<key>` (entry.data.price changed; event.changed_fields contains data.price). event.before.data.<key> / event.after.data.<key> "
        "carry short scalars only: long text, lists and secret-like fields read ‹elided› (the field still shows as changed).",
    }
    out["fields"] = condition_field_catalog()  # per trigger type, each field with what it means
    return out


# Step kinds whose fields and rules live in their own guide section (kind → section); `actions` names them in one line.
OWN_SECTION_KINDS = {"media": "media", "email": "email", "metric": "records", "snapshot": "records", "schema_check": "records"}


def _kind_doc(model) -> dict:
    return {"description": _doc(model), **_fields(model, skip=("kind",))}


def _step_doc(kind: str) -> dict:
    from marvin.schemas.group.automation_definition import ACTION_MODELS

    return _kind_doc(ACTION_MODELS[kind])


def _actions() -> dict:
    from marvin.schemas.group.automation_definition import ACTION_MODELS

    from .actions.entry import ENTRY_OPS, OP_SENDS, REVIEW_STATUS
    from .engine import MAX_ACTIONS

    kinds = {
        kind: {"description": f"{_first_sentence(_doc(model))} section={OWN_SECTION_KINDS[kind]} has its fields and rules."}
        if kind in OWN_SECTION_KINDS
        else _kind_doc(model)
        for kind, model in ACTION_MODELS.items()
    }
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
        "collect": COLLECT_NOTE,
        "fetch": FETCH_NOTE,
        "request": REQUEST_NOTE,
        "parallel": PARALLEL_NOTE,
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
REQUEST_NOTE = (
    "request calls any web API (fetch only reads public pages): an Airtable row, a Mailchimp or MailerLite subscribe, a "
    "link shortener — an API with a long-lived key (not one whose tokens expire within the hour, like Google's OAuth). "
    "Put the key in a workspace secret and name it — secret_ref: AIRTABLE_TOKEN (Bearer), or a "
    'header value "{{AIRTABLE_TOKEN}}" — never the key itself. body is JSON unless body_type is form or text; GET/HEAD take '
    "`query` instead. Later steps read ${steps.<id>.output.json.<field>} (an id the API returned) and .status. A non-2xx "
    "fails the run unless fail_on_error: false (then `when` on output.ok). Add retries: 2 for a flaky API, and an "
    "idempotency_key (e.g. airtable-${entry.id}) when a re-run must not add the row twice. {{SLUG}} resolves in headers "
    "and secret_ref, not the url. Needs an admin's role."
)
SOCIAL_NOTE = (
    "social posting is an integration step with capability: social.post (Instagram, a Facebook Page, Bluesky, Mastodon — "
    "whichever are connected). args: text (required), images (asset ids or slugs, ${steps.<id>.output.rows}, ${entry.image} "
    "or public https URLs — Marvin hands each network the asset's public URL and refuses a missing, trashed or private one), "
    "alt (one per image; defaults to the assets' alt text), link. Posting is public, so an Approval step must come before it "
    '(refused at save otherwise): a person approves the post text, e.g. message: "Post? ${steps.draft.output.post}". '
    "Leave `integration` out to post to every connected network, one after another; the output is results [{integration, "
    "network, posted, url, post_id, error}], posted_count, failed_count, and one failing doesn't stop the others — the step "
    "fails at the end unless fail_on_error: false. Add an idempotency_key (e.g. share-${entry.id}) so a re-run posts only "
    "where it hasn't. Name an `integration` to post to that one only. per_network overrides args for one network, keyed by "
    'the integration\'s slug or its network\'s name — {"bluesky": {"text": "${entry.title|truncate:280}"}} — because each '
    "network has its own limit (a network refuses a post that is too long or lacks a picture it needs, naming why; a dry "
    "run shows each one's answer and sends nothing). "
    "Engagement — answering comments — is more capabilities, each on ONE network, so the step must name its `integration` "
    "(never every network): social.comments (args since = the cursor it returned last time, limit, kinds; output items "
    "[{id, kind, post_id, post_url, author {id, handle, name}, text, created_at, url, network}] oldest first, and cursor), "
    "social.reply (comment_id = an item's id, text, private: true by default — a private reply to the commenter, false "
    "replies in the thread; a network that can't do the mode refuses with `unsupported`; output replied, reply_id, url), "
    "social.like (comment_id), social.hide (comment_id, hidden), social.delete_comment (comment_id), social.repost "
    "(post_id), social.message (to {id or handle}, text). reply, message, repost and delete_comment need an Approval step "
    "before them like a post does; comments, like and hide don't. A workflow can start on a new comment: the event "
    "social_comment_received (see the events section) carries the comment, and its steps name the connection as a template, "
    '"integration": "${event.integration}", with "comment_id": "${event.id}". Automatic keyword replies are not a workflow: '
    "they are the engagement engine's social-auto-reply rules (the Social engagement section of the integrations manual)."
)
SCHEMA_CHECK_NOTE = (
    "schema_check holds a JSON document against a JSON Schema: document: ${steps.page.output.json} (a fetch step's parsed "
    "body; a string holding JSON is read as JSON text) and schema: {…} inline, or schema_resource: <resource id or slug> "
    "whose metadata.schema holds it. Output valid, errors [{path, message}] (max_errors, default 20, at most 50), "
    "error_count, truncated, text. A document that doesn't fit is output — a `when` on valid (eq false) sends it to "
    "review with ${steps.<id>.output.text} — and fails the run only with fail_on_invalid: true. A malformed inline schema "
    "is refused when the workflow is saved. Formats aren't asserted; $ref reaches only into the schema; documents over "
    "100 KB are reported, not checked."
)
PARALLEL_NOTE = (
    "parallel: ${steps.<id>.output.branches.<name>.output.<key>} is a branch's last step. A "
    "check that should block must fail its step (schema_check fail_on_invalid). Gate: on_branch_failure continue, then "
    "`when` failed eq 0 goes ahead, failed gt 0 sends ${steps.<id>.output.text}."
)
EMAIL_NOTE = (
    "email writes to a member of this workspace — never an outside address: to: ${member.id} or ${member.email} (a member's id "
    "or the email they signed up with; a non-member fails the step), subject, body (markdown in the workspace's email layout), "
    "optional heading, button_text + button_link. It sends through the workspace's SMTP profile (no SMTP → the step fails) and "
    "once: the same event handled twice sends nothing more; once_per: welcome:${member.id} sends that person this step's email "
    "once, ever. Links by role: a `when` on ${member.role} (eq/in) per email step; ${site.url} is the public site, "
    "${site.app_url} the admin app. A dry run shows the rendered email (would_send) and sends nothing."
)
SNAPSHOT_NOTE = (
    "snapshot capture keeps the entry's content, status, collections, asset refs → "
    "${steps.<id>.output.snapshot_id} (an unchanged entry reuses its latest; 20 kept). restore: snapshot (that id; left out: "
    "the latest, or latest with `label`); parts content | collections | assets (default) | status (only when listed)."
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
    from .filters import guide as filters_guide

    return {
        "syntax": [
            '"${path}" as a whole value keeps the value\'s type; inside text ("Hi ${entry.title}") it is stringified.',
            '"$path" (whole value, no braces) also works. {{...}}, steps[...] and other forms are NOT templates.',
            '"${path|filter}" turns the value first; filters chain left to right and take arguments after a colon, '
            "comma-separated (quote one holding a comma or a bar): \"${entry.published_at|date:'%d %b %Y',Europe/Madrid}\", "
            '"${entry.title|truncate:60|default:\'Untitled\'}", "${entry.tags|join:\' · \'}", "${entry.url|url}".',
        ],
        "filters": filters_guide(),
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
        out["events"] = _events(workspace_refs(session, group_id))
    if "target" in want:
        out["target"] = _target()
    if "conditions" in want:
        out["conditions"] = _conditions()
    if "actions" in want:
        out["actions"] = _actions()
    if "media" in want:
        out["media"] = {"step": _step_doc("media"), "note": MEDIA_NOTE, "render_templates": _render_templates()}
    if "email" in want:
        out["email"] = {"step": _step_doc("email"), "note": EMAIL_NOTE}
    if "records" in want:
        out["records"] = {
            "metric": _step_doc("metric"),
            "snapshot": {**_step_doc("snapshot"), "note": SNAPSHOT_NOTE},
            "schema_check": {**_step_doc("schema_check"), "note": SCHEMA_CHECK_NOTE},
        }
    if "social" in want:
        out["social"] = {"note": SOCIAL_NOTE}
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
    from .validation import inner_steps, subject_of

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
                for path, inner in inner_steps(step):
                    _step_issues(inner, f"{list_key}[{i}].{path}", where, refs, issues, subject, after_approval=gated)
                after_approval = after_approval or step.get("kind") == "approval"
    return issues


def _trigger_issues(trig: dict, refs: WorkspaceRefs, issues: _Issues) -> None:
    from marvin.services.events.event_catalog import TRIGGERABLE_EVENT_TYPES, canonical_event_type

    ttype = trig.get("type", "event")
    event = trig.get("event")
    custom = [e["event_type"] for e in refs.custom_events]
    if ttype == "event" and isinstance(event, str) and canonical_event_type(event) not in {*TRIGGERABLE_EVENT_TYPES, *custom}:
        issues.add(
            "trigger.event",
            "trigger",
            f"“{event}” is not an event a workflow can trigger on. Events: {_close(event, sorted({*TRIGGERABLE_EVENT_TYPES, *custom}))}.",
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


def _operation_step_issues(step: dict, refs: WorkspaceRefs, subject: str, bad) -> None:
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
        if not step.get("entity_type") and etype not in supported and "form_submission" in supported:
            etype = "form_submission"  # a form operation acts on the run's submission
        if supported and etype not in supported:
            runs_on = f"this workflow runs on {etype}s" if not step.get("entity_type") else f"entity_type is {etype}"
            bad("op" if not step.get("entity_type") else "entity_type", f"“{step['op']}” runs on {' / '.join(supported)}, but {runs_on}.")


def _step_issues(
    step: dict, path: str, where: str, refs: WorkspaceRefs, issues: _Issues, subject: str = "entry", *, after_approval: bool = False
) -> None:
    def bad(key: str, message: str) -> None:
        issues.add(f"{path}.{key}" if key else path, where, message)

    _filter_issues(step, bad)
    kind = step.get("kind")
    if kind == "operation":
        _operation_step_issues(step, refs, subject, bad)
    elif kind == "entry":
        _entry_step_issues(step, refs, bad)
    elif kind == "emit_event":
        _emit_event_issues(step, refs, bad)
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
        if _templated(slug):
            _templated_integration_issues(step, after_approval, bad)
        elif not slug and capability and not key:
            _every_integration_issues(capability, refs, bad, after_approval)
            _engagement_args_issues(step, capability, bad)
        elif row is None:
            bad("integration", f"No integration “{slug}” here. Integrations: {_close(str(slug), [i['slug'] for i in refs.integrations])}.")
        elif not key and capability:
            if row.get("capabilities") is not None and capability not in row["capabilities"]:
                able = ", ".join(i["slug"] for i in refs.integrations if capability in (i.get("capabilities") or [])) or "(none here)"
                bad("capability", f"“{slug}” can't {capability}. Integrations that can: {able}.")
            else:
                _gated_capability_issue(capability, after_approval, bad)
                _engagement_args_issues(step, capability, bad)
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
    elif kind == "request":
        _request_step_issues(step, bad)
    elif kind == "email":
        _email_step_issues(step, bad)


def _templated_integration_issues(step: dict, after_approval: bool, bad) -> None:
    """`integration: "${event.integration}"`: the connection is known only when the run starts, so what it can do is checked then.
    Only a capability step may take one (an action key belongs to one provider); the approval and argument rules apply as ever."""
    capability = step.get("capability")
    if step.get("action") or not capability:
        bad(
            "integration",
            "A templated `integration` (such as ${event.integration}) goes with a `capability` step; an action key belongs to one provider.",
        )
        return
    _gated_capability_issue(capability, after_approval, bad)
    _engagement_args_issues(step, capability, bad)


def _gated_capability_issue(capability: str, after_approval: bool, bad) -> None:
    """A capability that speaks or destroys in public (social.post, .reply, .message, .repost, .delete_comment) runs only
    once a person approved the run: an Approval step before it."""
    from marvin.services.integrations.alert_routing import GATED_CAPABILITIES
    from marvin.services.integrations.social import SOCIAL_DELETE_COMMENT, SOCIAL_MESSAGE, SOCIAL_REPLY, SOCIAL_REPOST

    if capability in GATED_CAPABILITIES and not after_approval:
        does = {
            SOCIAL_REPLY: "replies to a comment",
            SOCIAL_MESSAGE: "sends a message",
            SOCIAL_REPOST: "reposts",
            SOCIAL_DELETE_COMMENT: "deletes a comment (it can't be undone)",
        }.get(capability, "posts publicly")
        bad("capability", f"“{capability}” {does} and needs a person's approval: put an Approval step before it (it runs once approved).")


def _engagement_args_issues(step: dict, capability: str, bad) -> None:
    """A social engagement capability acts on one network's own comment or post: it names its `integration` (it never runs
    on every network) and carries the arguments it can't run without, as values or templates."""
    from marvin.services.integrations.social import ENGAGEMENT_CAPABILITIES, REQUIRED_ARGS

    if capability not in ENGAGEMENT_CAPABILITIES:
        return
    if not step.get("integration"):
        bad(
            "integration", f"“{capability}” acts on one network's own comment or post, so it needs an `integration` (it never runs on every network)."
        )
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    if missing := [k for k in REQUIRED_ARGS.get(capability, ()) if args.get(k) in (None, "", {}, [])]:
        bad("args", f"“{capability}” needs {', '.join(missing)} in args (a value, or a template such as ${{steps.read.output.items[0].id}}).")


def _every_integration_issues(capability: str, refs: WorkspaceRefs, bad, after_approval: bool) -> None:
    """A capability step with no `integration` runs on every connected integration that offers it: at least one must, and a
    gated capability needs its Approval step. (An engagement capability never fans out: its step is refused for that
    by `_engagement_args_issues`, not for having no integration that can.)"""
    from marvin.services.integrations.social import ENGAGEMENT_CAPABILITIES

    able = [i for i in refs.integrations if i.get("enabled") and capability in (i.get("capabilities") or [])]
    known = all(i.get("capabilities") is not None for i in refs.integrations)
    if not able and known and capability not in ENGAGEMENT_CAPABILITIES:
        bad("capability", f"No connected integration can {capability} (Settings → Integrations): connect one, or name an `integration`.")
    _gated_capability_issue(capability, after_approval, bad)


def _filter_issues(step: dict, bad) -> None:
    """A template filter that won't work (``${entry.title|tuncate:40}``) is refused at save: at run time it would quietly
    give nothing. A nested step (a parallel branch's, a repeat's) is checked as its own step."""
    from .filters import filter_problem, split_expression
    from .matcher import _BRACED

    def walk(value: Any, key: str) -> None:
        if isinstance(value, str) and "|" in value:
            for expr in _BRACED.findall(value):
                for text in split_expression(expr)[1:]:
                    if problem := filter_problem(text):
                        bad(key, f"In ${{{expr}}}: {problem}")
        elif isinstance(value, dict):
            for v in value.values():
                walk(v, key)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)

    for key, value in step.items():
        if key not in ("steps", "branches", "actions"):
            walk(value, key)


def _email_step_issues(step: dict, bad) -> None:
    """An Email step writes to a member, named by id or email — a typed-in word is neither (a member is checked when it runs)."""
    to = step.get("to")
    if isinstance(to, str) and to.strip() and not _templated(to) and "@" not in to:
        try:
            uuid.UUID(to.strip())
        except ValueError:
            bad("to", f"“{to}” is not a member's id or email address. Use ${{member.id}}, ${{member.email}} or a member's email.")
    link = step.get("button_link")
    if isinstance(link, str) and link.strip() and not _templated(link) and urlparse(link.strip()).scheme not in ("http", "https"):
        bad("button_link", f"“{link}” isn't a web address: it needs http:// or https://.")


def _fetch_step_issues(step: dict, bad) -> None:
    url = step.get("url")
    if isinstance(url, str) and not _templated(url) and urlparse(url.strip()).scheme not in ("http", "https"):
        bad("url", f"“{url}” isn't a web address: it needs http:// or https://.")


def _request_step_issues(step: dict, bad) -> None:
    """The address, and no key typed into a header: a credential belongs in a workspace secret, named by {{SLUG}}."""
    _fetch_step_issues(step, bad)
    from .actions.webhook import _CREDENTIAL_HEADER

    for name, value in (step.get("headers") or {}).items() if isinstance(step.get("headers"), dict) else ():
        text = str(value or "").strip()
        if _CREDENTIAL_HEADER.search(str(name)) and text and "{{" not in text and not _templated(text):
            bad("headers", f"Header {name} holds a credential typed in: keep it in a workspace secret and write {{{{SLUG}}}} instead.")


def _emit_event_issues(step: dict, refs: WorkspaceRefs, bad) -> None:
    """An Emit event step names an event a workflow may send; a workspace's own event takes only its registered fields."""
    from marvin.services.events.event_catalog import EMITTABLE_EVENT_TYPES, canonical_event_type

    event = step.get("event")
    if not isinstance(event, str):
        return
    own = {e["event_type"]: e["fields"] for e in refs.custom_events}
    sendable = {*EMITTABLE_EVENT_TYPES, *own}
    if canonical_event_type(event) not in sendable:
        bad("event", f"“{event}” can't be sent by a workflow. Emittable: {_close(event, sorted(sendable))}.")
    elif event in own and isinstance(step.get("payload"), dict):
        if unknown := sorted(k for k in step["payload"] if k not in own[event]):
            bad("payload", f"{event} has no field {', '.join(unknown)}. Fields: {', '.join(own[event]) or 'none'}.")


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
            "attach_asset needs `asset`: the asset's id or slug — a template to a step's picture works (${steps.<id>.output.images.0.asset.id}).",
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
