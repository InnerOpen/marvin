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
from typing import Any

# What the guide offers in detail (`section=`); without one it gives a bounded overview of all of them.
SECTIONS = ("shape", "triggers", "events", "target", "conditions", "actions", "templates", "workspace", "examples")

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
    return [op for op in list_operations() if AUTOMATION_SOURCE in op.invocation_sources]


def _integration_actions(provider_slug: str) -> list[dict] | None:
    """A provider's actions a workflow can run (approval-gated ones can't run unattended); None when the
    provider isn't installed."""
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
        if getattr(a, "requires_approval", False):
            continue
        schema = a.input_schema or {}
        props = schema.get("properties") or {}
        out.append(
            {
                "action": a.key,
                "label": a.label,
                "description": a.description,
                "args": {k: (v.get("type") if isinstance(v, dict) else None) or "any" for k, v in props.items()},
                "required": list(schema.get("required") or []),
            }
        )
    return out


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
    refs.entry_types = [
        {"slug": t.slug, "name": t.name, "fields": [f.get("key") for f in (t.schema_json or {}).get("fields", []) if isinstance(f, dict)]}
        for t in types_q.limit(REF_LIMIT)
    ]
    for row in session.query(IntegrationModel).filter_by(group_id=group_id).order_by(IntegrationModel.name).limit(REF_LIMIT):
        refs.integrations.append(
            {
                "slug": row.slug,
                "name": row.name,
                "provider": row.provider,
                "enabled": bool(row.enabled),
                "actions": _integration_actions(row.provider),
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
        ],
    }


def _triggers(detail: bool) -> dict:
    from marvin.schemas.group.automation_definition import TRIGGER_MODELS
    from marvin.schemas.platform.scheduled_tasks import ScheduledTaskCreate

    out: dict[str, Any] = {kind: {"description": _doc(model), **_fields(model, skip=("type",))} for kind, model in TRIGGER_MODELS.items()}
    out["schedule"]["schedule_types"] = list(typing.get_args(ScheduledTaskCreate.model_fields["schedule_type"].annotation))
    if detail:
        from .validation import condition_field_catalog

        for kind, fields in condition_field_catalog().items():
            if kind in out:
                out[kind]["condition_fields"] = [f["field"] for f in fields]
    return out


def _events(detail: bool) -> dict:
    from marvin.services.events.event_catalog import CATALOG_BY_TYPE, offered_emittable, trigger_groups

    if detail:
        groups: dict[str, Any] = {g: {e: CATALOG_BY_TYPE[e].description for e in names} for g, names in trigger_groups().items()}
    else:
        groups = trigger_groups()
    return {
        "triggerable": groups,
        "emittable": offered_emittable(),
        "note": "An event trigger names one triggerable event. describe_event gives an event's `event.*` fields.",
    }


def _target() -> dict:
    from marvin.schemas.platform.entries import ENTRY_STATUSES
    from marvin.services.entries.query import SPEC_KEY_NOTES

    from .selector import MAX_TARGET_ENTITIES

    return {
        "entity": "entry (the only kind a target selects)",
        "query": SPEC_KEY_NOTES,
        "statuses": sorted(ENTRY_STATUSES),
        "limit": f"at most {MAX_TARGET_ENTITIES} entries per run",
        "note": "Query values may be templates. Each match runs the steps as `entry` (and `event.entry_id`).",
    }


def _conditions(detail: bool) -> dict:
    from .matcher import _OPS
    from .validation import condition_field_catalog

    out: dict[str, Any] = {
        "form": "a list (all must hold) of {field, op, value}; groups: {all: [...]}, {any: [...]}, {not: {...}}",
        "ops": list(_OPS),
        "field": "a bare dotted path (no $), e.g. entry.status, entry.data.<field>, event.payload.<key>",
        "note": "Conditions are checked before any step runs, so steps.* / previous.* aren't available in them.",
    }
    fields = condition_field_catalog()
    # Per trigger type; the detail adds what each field means.
    out["fields"] = fields if detail else {k: [f["field"] for f in v] for k, v in fields.items()}
    return out


def _actions(detail: bool) -> dict:
    from marvin.schemas.group.automation_definition import ACTION_MODELS

    from .actions.entry import ENTRY_OPS, ITEM_OP_SENDS, OP_SENDS, REVIEW_STATUS
    from .engine import MAX_ACTIONS

    kinds = {kind: {"description": _doc(model), **_fields(model, skip=("kind",))} for kind, model in ACTION_MODELS.items()}
    if not detail:  # names only; section="actions" has the types
        kinds = {k: {"description": v["description"], "required": list(v["required"]), "optional": list(v["optional"])} for k, v in kinds.items()}
    entry_ops: dict[str, Any] = {}
    for op, sends in OP_SENDS.items():
        status = ENTRY_OPS.get(op) or (REVIEW_STATUS if op == "request_review" else None)
        entry_ops[op] = {"sets_status": status, "sends": list(sends)} if detail else (f"status → {status}" if status else "")
    entry_ops_note = (
        "`unpublish` and `restore` set status draft (there is no op to set any other status); add/remove_from_collection "
        "need collection_slug; set_metadata needs `metadata`, set_data needs `data` (the type's fields); request_review takes `reason`."
    )
    items = sorted({op for _kind, op in ITEM_OP_SENDS})
    return {
        "kinds": kinds,
        "entry_ops": entry_ops,
        "entry_ops_note": entry_ops_note,
        "asset_resource_ops": f"{', '.join(items)} with entity_type asset | resource",
        "max_steps": MAX_ACTIONS,
        "step_id": "Give a step an `id` to read its output later as ${steps.<id>.output.<key>}.",
    }


def _templates() -> dict:
    from .engine import TEMPLATE_NAMESPACES

    return {
        "syntax": [
            '"${path}" as a whole value keeps the value\'s type; inside text ("Hi ${entry.title}") it is stringified.',
            '"$path" (whole value, no braces) also works. {{...}}, steps[...] and other forms are NOT templates.',
        ],
        "namespaces": TEMPLATE_NAMESPACES,
        "where": "step fields (input, args, body, metadata, data, entity_slug, collection_slug, reason…), target.query values, condition values",
    }


def _workspace(refs: WorkspaceRefs, detail: bool) -> dict:
    integrations = []
    for i in refs.integrations:
        actions = i["actions"]
        if not detail and actions is not None:
            actions = [a["action"] for a in actions]
        integrations.append({**i, "actions": actions if actions is not None else "provider not installed"})
    return {
        "collections": [c["slug"] for c in refs.collections] if not detail else refs.collections,
        "entry_types": refs.entry_types if detail else {t["slug"]: t["fields"] for t in refs.entry_types},
        "integrations": integrations,
        "outgoing_webhooks": refs.outgoing_webhooks,
        "incoming_webhooks": refs.incoming_webhooks,
        "workflows": [{"slug": w["slug"], "name": w["name"], "enabled": w["enabled"]} for w in refs.workflows],
        "operations": (
            "AI operations can't run from workflows here (AI is off, or its automation source is disabled)"
            if refs.operations is None
            else (refs.operations if detail else [o["op"] for o in refs.operations])
        ),
        "handlers": refs.handlers if detail else [h["task"] for h in refs.handlers],
    }


# Worked definitions — kept honest by a test that drafts each one (structure, keys and references).
EXAMPLES: dict[str, dict] = {
    "Move every entry with an image back to draft": {
        "trigger": {"type": "manual"},
        "target": {"entity": "entry", "query": {"has_images": True, "status": "published"}},
        "actions": [{"kind": "entry", "op": "unpublish"}],
    },
    "When a recipe is published, summarise it and add it to a collection": {
        "trigger": {"type": "event", "event": "entry_published"},
        "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "recipe"}],
        "actions": [
            {"kind": "operation", "op": "generate-summary", "write_back": True},
            {"kind": "entry", "op": "add_to_collection", "collection_slug": "featured"},
        ],
    },
    "Every hour, rebuild the site": {
        "trigger": {"type": "schedule", "schedule_type": "interval", "schedule_config": {"interval_seconds": 3600}},
        "actions": [{"kind": "handler", "task": "request_site_rebuild"}],
    },
    "A webhook call finds an entry by slug and archives it": {
        "trigger": {"type": "incoming_webhook", "webhook": "any"},
        "actions": [{"kind": "entry", "op": "archive", "entity_slug": "${event.payload.slug}", "id": "archive"}],
        "on_failure": [{"kind": "entry", "op": "request_review", "entity_slug": "${event.payload.slug}", "reason": "${error.message}"}],
    },
}


def authoring_guide(session, group_id, section: str | None = None) -> dict:
    """The guide: every section in brief, or one in detail. Raises ValueError for an unknown section."""
    if section and section not in SECTIONS:
        raise ValueError(f"unknown section '{section}' — one of: {', '.join(SECTIONS)}")
    detail = section is not None
    want = (section,) if section else SECTIONS
    out: dict[str, Any] = {}
    if "shape" in want:
        out["shape"] = _shape()
    if "triggers" in want:
        out["triggers"] = _triggers(detail)
    if "events" in want:
        out["events"] = _events(detail)
    if "target" in want:
        out["target"] = _target()
    if "conditions" in want:
        out["conditions"] = _conditions(detail)
    if "actions" in want:
        out["actions"] = _actions(detail)
    if "templates" in want:
        out["templates"] = _templates()
    if "workspace" in want:
        out["workspace"] = _workspace(workspace_refs(session, group_id), detail)
    if "examples" in want:
        out["examples"] = {
            "note": "Patterns, not this workspace: swap in its own event, collection, entry type and operation names.",
            **(EXAMPLES if detail else dict(list(EXAMPLES.items())[:1])),
        }
    if not detail:
        out["more"] = (
            "Call again with section= one of " + ", ".join(SECTIONS) + " for detail: event descriptions, field types, what each entry op "
            "sends, integration action args, more examples. Then call draft_workflow."
        )
    return out


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
    """The valid options, the ones sharing a word with `value` first, capped."""
    words = set(str(value).replace("-", "_").split("_"))
    ranked = sorted(options, key=lambda o: (not words & set(o.replace("-", "_").split("_")), o))
    shown = ranked[:limit]
    more = f" (+{len(options) - limit} more)" if len(options) > limit else ""
    return ", ".join(shown) + more if shown else "(none in this workspace)"


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
    refs = refs or workspace_refs(session, group_id)
    issues = _Issues()
    _trigger_issues(definition.get("trigger") or {}, refs, issues)
    if isinstance(definition.get("target"), dict):
        _target_issues(definition["target"], refs, issues)
    _condition_issues(definition.get("conditions"), "conditions", issues)
    for list_key, where in (("actions", "action"), ("on_failure", "on_failure")):
        for i, step in enumerate(definition.get(list_key) or []):
            if isinstance(step, dict):
                _step_issues(step, f"{list_key}[{i}]", where, refs, issues)
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
    from marvin.schemas.platform.entries import ENTRY_STATUSES
    from marvin.services.entries.query import SPEC_KEYS

    if target.get("entity", "entry") != "entry":
        issues.add("target.entity", "target", "A target selects entries only (entity: entry).")
    type_slugs = [t["slug"] for t in refs.entry_types]
    spellings = {s.replace("-", "_") for s in type_slugs}
    collections = {c["slug"] for c in refs.collections} | {c["name"] for c in refs.collections}
    for key, value in (target.get("query") or {}).items():
        path = f"target.query.{key}"
        if key not in SPEC_KEYS:
            issues.add(path, "target", f"“{key}” is not an entry query key. Keys: {_close(key, list(SPEC_KEYS))}.")
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


def _step_issues(step: dict, path: str, where: str, refs: WorkspaceRefs, issues: _Issues) -> None:
    def bad(key: str, message: str) -> None:
        issues.add(f"{path}.{key}" if key else path, where, message)

    kind = step.get("kind")
    if kind == "operation":
        if refs.operations is None:
            bad("", "AI operations can't run from workflows in this workspace (AI is off, or its automation source is disabled).")
        elif step.get("op") not in {o["op"] for o in refs.operations}:
            bad("op", f"No AI operation “{step.get('op')}”. Operations: {_close(str(step.get('op')), [o['op'] for o in refs.operations])}.")
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
        slug, key = step.get("integration"), step.get("action")
        row = next((i for i in refs.integrations if i["slug"] == slug), None)
        if row is None:
            bad("integration", f"No integration “{slug}” here. Integrations: {_close(str(slug), [i['slug'] for i in refs.integrations])}.")
        elif row["actions"] is not None and key not in {a["action"] for a in row["actions"]}:
            actions = ", ".join(a["action"] for a in row["actions"]) or "(none)"
            bad("action", f"“{slug}” has no action “{key}” a workflow can run. Actions: {actions}.")


def _entry_step_issues(step: dict, refs: WorkspaceRefs, bad) -> None:
    from .actions.entry import ITEM_OP_SENDS

    op = step.get("op")
    etype = step.get("entity_type", "entry")
    if etype != "entry" and (etype, op) not in ITEM_OP_SENDS:
        bad("entity_type", f"Only trash and restore act on an {etype}; “{op}” acts on entries (drop entity_type).")
    if op in ("add_to_collection", "remove_from_collection"):
        ref = step.get("collection_slug")
        known = {c["slug"] for c in refs.collections} | {c["name"] for c in refs.collections}
        if not ref and not step.get("collection_id"):
            bad("collection_slug", f"“{op}” needs collection_slug.")
        elif isinstance(ref, str) and not _templated(ref) and ref not in known:
            bad("collection_slug", f"No collection “{ref}” here. Collections: {_close(ref, [c['slug'] for c in refs.collections])}.")
    if op == "set_metadata" and not step.get("metadata"):
        bad("metadata", "set_metadata needs `metadata`: the keys to merge into the entry's metadata.")
    if op == "set_data" and not step.get("data"):
        bad("data", "set_data needs `data`: the entry type's field keys and their new values.")


def draft_issues(session, group_id, definition: dict) -> list[dict]:
    """Everything that stops an agent's draft: the REST write path's structural gate first (exactly the
    function `POST /api/automations` calls), then unknown keys and unknown references. Empty: draftable."""
    from .validation import structural_issues, unknown_key_issues

    issues = structural_issues(definition)
    if issues:
        return issues
    return unknown_key_issues(definition) + reference_issues(session, group_id, definition)
