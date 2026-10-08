"""Per-trigger condition-field catalog + coherence validation for Flavor B automations.

The matcher context differs by trigger: an entry-lifecycle event exposes ``entry.*``, an incoming
webhook exposes ``event.payload.*``, a chained trigger exposes ``event.automation_slug``, and so on.
Conditions are authored as free-text dotted paths, so it is easy to reference a namespace the
trigger never provides — e.g. ``entry.entry_type`` under an ``incoming_webhook`` trigger — which
then *silently never matches* (the path resolves to None). This module:

  * advertises the fields available per trigger (``condition_field_catalog``) so the builder can
    offer a guided picker instead of a blank text box, and
  * validates a definition (``validate_definition``) and returns human-readable issues, so the same
    mismatch surfaces as a warning at author time rather than a workflow that quietly does nothing.

Validation is advisory (warnings), not a hard gate: payload shapes are caller-defined and advanced
authors may map fields the catalog can't know about. The engine remains the source of truth for
execution; this only helps authors avoid the silent-no-op footgun.
"""

from typing import Any

from .matcher import _OPS

# Fields conditions can reference, grouped by the namespace each trigger's context exposes.
# NOTE: conditions are evaluated BEFORE any action runs, so `previous.*` / `steps.*` are never
# available here — only trigger-provided context is.

_EVENT_TYPE_FIELD = {
    "field": "event.event_type",
    "label": "Event type",
    "description": "The machine name of the triggering event.",
}

# Entry-lifecycle triggers load the referenced entry into the context as `entry.*`.
_ENTRY_FIELDS = [
    {"field": "entry.entry_type", "label": "Entry type", "description": "The entry's type slug, e.g. 'recipe'."},
    {"field": "entry.status", "label": "Status", "description": "draft | published | archived | inbox | trashed…"},
    {"field": "entry.title", "label": "Title", "description": "The entry title (use with 'contains')."},
    {"field": "entry.slug", "label": "Slug", "description": "The entry's URL slug."},
    {"field": "entry.id", "label": "Entry ID", "description": "The entry's UUID."},
    # Change detection (populated on entry_updated). before/after carry only the changed fields, so
    # `event.after.status == review` means "status changed to review".
    {
        "field": "event.after.status",
        "label": "Status changed to…",
        "description": "New status, only if it changed (e.g. 'review'). Empty if status didn't change.",
    },
    {"field": "event.before.status", "label": "Status changed from…", "description": "Prior status, only if it changed (e.g. 'draft')."},
    {
        "field": "event.changed_fields",
        "label": "Changed fields",
        "description": "Which fields changed — use with 'contains' (e.g. contains 'status').",
    },
]

_WEBHOOK_FIELDS = [
    {"field": "event.webhook_slug", "label": "Webhook", "description": "Which incoming webhook fired."},
    {
        "field": "event.payload.",
        "label": "Payload field…",
        "description": "A field from the POST body, e.g. event.payload.type. Shape is caller-defined.",
    },
]

_CHAINED_FIELDS = [
    {"field": "event.automation_slug", "label": "Source workflow", "description": "The workflow that just ran / failed."},
]

# What each trigger type puts in the match context, keyed by trigger.type.
# The `namespaces` set is used for validation; `fields` is the builder's suggestion list.
_TRIGGER_CONTEXT: dict[str, dict] = {
    "event": {"namespaces": {"event", "entry"}, "fields": [_EVENT_TYPE_FIELD, *_ENTRY_FIELDS]},
    "incoming_webhook": {"namespaces": {"event"}, "fields": [_EVENT_TYPE_FIELD, *_WEBHOOK_FIELDS]},
    "chained": {"namespaces": {"event"}, "fields": [_EVENT_TYPE_FIELD, *_CHAINED_FIELDS]},
    "on_error": {"namespaces": {"event"}, "fields": [_EVENT_TYPE_FIELD, *_CHAINED_FIELDS]},
    "manual": {"namespaces": {"event"}, "fields": [_EVENT_TYPE_FIELD]},
    "schedule": {"namespaces": {"event"}, "fields": [_EVENT_TYPE_FIELD]},
    "mcp": {"namespaces": {"event"}, "fields": [_EVENT_TYPE_FIELD]},
}

# Triggers whose context includes a specific entry (so entry.* resolves + entry-shaped actions work).
_ENTRY_TRIGGERS = {"event"}


def condition_field_catalog() -> dict[str, list[dict]]:
    """Suggested condition fields per trigger type — advertised by /api/automations/options."""
    return {ttype: cfg["fields"] for ttype, cfg in _TRIGGER_CONTEXT.items()}


def _namespaces_for(trigger_type: str) -> set[str]:
    return _TRIGGER_CONTEXT.get(trigger_type, _TRIGGER_CONTEXT["event"])["namespaces"]


def _issue(level: str, message: str, where: str, index: int | None = None) -> dict:
    out: dict[str, Any] = {"level": level, "message": message, "where": where}
    if index is not None:
        out["index"] = index
    return out


def validate_definition(definition: dict | None) -> list[dict]:
    """Return advisory issues for a definition (never raises). Empty list = looks coherent.

    Each issue is ``{level: "warning"|"error", message, where, index?}``. The most valuable check is
    a condition (or entry-shaped action) that references an ``entry`` the trigger never provides.
    """
    issues: list[dict] = []
    definition = definition or {}
    trig = definition.get("trigger") or {}
    ttype = trig.get("type", "event")
    namespaces = _namespaces_for(ttype)
    # A `target` selector that yields entries hydrates `entry.*` for every matched row — so entry
    # conditions/actions are valid even under a trigger (webhook/manual) that has no inherent entry.
    target = definition.get("target") or {}
    has_target_entry = bool(target) and target.get("entity", "entry") == "entry"
    has_entry = (ttype in _ENTRY_TRIGGERS) or has_target_entry
    if has_target_entry:
        namespaces = namespaces | {"entry"}

    # ── Conditions ────────────────────────────────────────────────────────────
    for i, cond in enumerate(definition.get("conditions") or []):
        if not isinstance(cond, dict):
            continue
        field = str(cond.get("field") or "")
        seg = field.split(".")[0] if field else ""
        op = cond.get("op", "eq")

        if not field:
            issues.append(_issue("warning", "Condition has no field — it won't do anything.", "condition", i))
        elif seg in ("previous", "steps"):
            issues.append(
                _issue(
                    "warning",
                    f"Condition uses “{field}”, but step outputs aren't available in conditions (conditions are evaluated before any step runs).",
                    "condition",
                    i,
                )
            )
        elif seg == "entry" and not has_entry:
            issues.append(
                _issue(
                    "warning",
                    f"Condition uses “{field}”, but this {_pretty(ttype)} trigger has no entry — "
                    "this condition will never match. Use event.payload.* (webhook) or an entry trigger.",
                    "condition",
                    i,
                )
            )
        elif seg and seg not in namespaces and seg not in ("event", "entry", "site"):
            issues.append(
                _issue(
                    "warning",
                    f"Condition field “{field}” isn't in this trigger's context (available: {', '.join(sorted(namespaces))}).",
                    "condition",
                    i,
                )
            )

        if op not in _OPS:
            issues.append(_issue("warning", f"Unknown condition operator “{op}”.", "condition", i))

    # ── Actions ───────────────────────────────────────────────────────────────
    from .engine import MAX_ACTIONS

    actions = definition.get("actions") or []
    if not actions:
        issues.append(_issue("warning", "This workflow has no steps, so it does nothing.", "action"))
    elif len(actions) > MAX_ACTIONS:
        issues.append(
            _issue(
                "warning",
                f"This workflow has {len(actions)} steps, but only the first {MAX_ACTIONS} will run "
                f"(the rest are ignored). Split it into chained workflows.",
                "action",
            )
        )

    for i, act in enumerate(actions):
        issues.extend(_step_issues(act, i, "action", ttype, has_entry))
    # Steps that run when one above fails — same entry, same checks.
    on_failure = definition.get("on_failure") or []
    if len(on_failure) > MAX_ACTIONS:
        issues.append(_issue("warning", f"On failure has {len(on_failure)} steps, but only the first {MAX_ACTIONS} will run.", "on_failure"))
    for i, act in enumerate(on_failure):
        issues.extend(_step_issues(act, i, "on_failure", ttype, has_entry))

    return issues


def _step_issues(act, i: int, where: str, ttype: str, has_entry: bool) -> list[dict]:
    """Advisory issues for one step (of `actions` or `on_failure`)."""
    issues: list[dict] = []
    if not isinstance(act, dict):
        return issues
    kind = act.get("kind")
    # An AI `operation` or an `entry` action operates on an entity — both default to
    # $event.entry_id. Under a trigger with no entry (and no target selector), that resolves to
    # nothing unless the author targets one from the payload, by slug (entity_slug — preferred,
    # human-readable), by id (entity_id), or by a run-time lookup (entity_query, entry actions).
    targets_own_entry = any(act.get(k) for k in ("entity_slug", "entity_id", "entity_query"))
    if kind in ("operation", "entry") and not has_entry and not targets_own_entry:
        what = act.get("op", kind)
        issues.append(
            _issue(
                "warning",
                f"Step “{what}” runs on an entry, but this {_pretty(ttype)} trigger has none. "
                "Point it at one with entity_slug (e.g. $event.payload.entry_slug) or entity_query, "
                "add a Run-on target, or use an entry trigger.",
                where,
                i,
            )
        )
    # A collection-membership entry action needs a target collection.
    if (
        kind == "entry"
        and act.get("op") in ("add_to_collection", "remove_from_collection")
        and not act.get("collection_slug")
        and not act.get("collection_id")
    ):
        issues.append(
            _issue(
                "warning",
                f"Step “{act.get('op')}” needs a target collection — set collection_slug (e.g. 'featured' or $event.payload.collection_slug).",
                where,
                i,
            )
        )
    return issues


def _pretty(trigger_type: str) -> str:
    return {"incoming_webhook": "incoming-webhook", "on_error": "on-error"}.get(trigger_type, trigger_type)


# ── Structural validation (from the Pydantic source of truth) ─────────────────
# validate_definition (above) is advisory/semantic: "this is coherent but won't match anything".
# structural_issues is the shape gate: "this isn't a well-formed definition at all" (unknown action
# kind, missing required field, wrong type). It's derived entirely from AutomationDefinition, so the
# models are the single source of truth — and the write path gates on it (create/update 422).

_WHERE_BY_HEAD = {"actions": "action", "on_failure": "on_failure", "conditions": "condition", "trigger": "trigger"}


def issue_path(loc: tuple[Any, ...], data: Any) -> str:
    """A Pydantic error location as the path an author reads — ``actions[0].op`` rather than
    ``actions.0.entry.op``. A discriminated union puts the branch's tag (``entry``) or a union member's
    type name (``list[Condition]``) in the location; those aren't keys of the definition, so a segment is
    kept only while it walks the data — or when it is the last one (a missing required field)."""
    parts: list[str] = []
    cur = data
    for i, seg in enumerate(loc):
        if isinstance(seg, int) and isinstance(cur, list) and 0 <= seg < len(cur):
            parts.append(f"[{seg}]")
            cur = cur[seg]
        elif isinstance(cur, dict) and seg in cur:
            parts.append(f".{seg}" if parts else str(seg))
            cur = cur[seg]
        elif i == len(loc) - 1 and isinstance(seg, str) and seg.isidentifier() and seg[:1].islower():
            parts.append(f".{seg}" if parts else seg)
    return "".join(parts)


def _structural_issue(err: dict, definition: Any = None) -> dict:
    """Map one Pydantic error to the {level, message, where, index?, path} issue shape used everywhere."""
    loc: tuple[Any, ...] = err.get("loc", ()) or ()
    where = _WHERE_BY_HEAD.get(loc[0], "trigger") if loc else "trigger"
    index = loc[1] if len(loc) > 1 and isinstance(loc[1], int) else None
    path = ".".join(str(p) for p in loc)
    msg = err.get("msg", "invalid")
    issue: dict[str, Any] = {"level": "error", "message": f"{path}: {msg}" if path else msg, "where": where}
    if index is not None:
        issue["index"] = index
    issue["path"] = issue_path(loc, definition)
    return issue


def structural_issues(definition: dict | None) -> list[dict]:
    """Shape errors from the Pydantic definition model, as ERROR-level issues (same shape as
    ``validate_definition``'s warnings). Empty list = the definition is structurally well-formed."""
    from pydantic import ValidationError

    from marvin.schemas.group.automation_definition import AutomationDefinition

    try:
        AutomationDefinition.model_validate(definition or {})
        return []
    except ValidationError as e:
        return [_structural_issue(err, definition) for err in e.errors() if not _other_branch(err.get("loc", ()), definition)]


def _other_branch(loc: tuple[Any, ...], data: Any) -> bool:
    """An error from the union member the value plainly isn't — `conditions` takes a list or a single
    group, and a list's error under the single-group member (or the reverse) only adds noise."""
    cur = data
    for seg in loc:
        if isinstance(seg, str) and not (isinstance(cur, dict) and seg in cur) and ("[" in seg or seg[:1].isupper()):
            return seg.startswith("list[") != isinstance(cur, list)
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(seg, int) and isinstance(cur, list) and 0 <= seg < len(cur):
            cur = cur[seg]
    return False


def unknown_key_issues(definition: dict | None) -> list[dict]:
    """Keys the definition model doesn't declare, as ERROR-level issues with their path.

    The models allow extra keys (`extra="allow"`) so a forward-compatible definition still saves through
    the API, and nothing reads them: a step written as ``{"type": "find_entries"}`` or a top-level
    ``"steps"`` list is silently ignored. Hand-written JSON may want that leniency; an agent drafting a
    workflow does not — an unknown key there is an invented shape — so the agent's draft path checks this
    on top of :func:`structural_issues`. Read off the validated models (``model_extra``), so it follows
    the models. Only for a structurally valid definition; call :func:`structural_issues` first."""
    from pydantic import BaseModel, ValidationError

    from marvin.schemas.group.automation_definition import AutomationDefinition

    try:
        model = AutomationDefinition.model_validate(definition or {})
    except ValidationError:
        return []

    issues: list[dict] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
            return
        if not isinstance(node, BaseModel):
            return
        fields = {f.alias or name: name for name, f in type(node).model_fields.items()}  # key as written → attribute
        for key in node.model_extra or {}:
            head = (path or key).split("[")[0].split(".")[0]
            issues.append(
                {
                    "level": "error",
                    "message": f"“{key}” is not a field here, so it would be ignored. Fields: {', '.join(sorted(fields))}.",
                    "where": _WHERE_BY_HEAD.get(head, "definition"),
                    "path": f"{path}.{key}" if path else key,
                }
            )
        for key, attr in fields.items():
            walk(getattr(node, attr), f"{path}.{key}" if path else key)

    walk(model, "")
    return issues
