"""`entry` action — act on an entry. No AI.

Two families, both through EntryService so the right events fire and chains stay reliable:
  * **status** — publish / unpublish / archive / restore (emits entry_published / entry_unpublished /
    entry_archived / entry_restored), and
  * **collection membership** — add_to_collection / remove_from_collection (emits
    entry_added_to_collection / entry_removed_from_collection), idempotent.
  * **field writes** — set_metadata (merge into metadata_json) and set_data (merge into the schema
    fields in data_json, validated against the entry type — e.g. a select field's new option).

It targets the triggering entry (`$event.entry_id`) by default, an entry by slug (`entity_slug`), or
an explicit id — so it pairs with the target selector to act on a whole query: "add all drafts
matching X to the Featured collection" is a `target` selecting drafts + an add_to_collection action,
since each matched entry is bound to `$event.entry_id` for its fan-out row. Collection ops take a
`collection_slug` (or `collection_id`), which may itself be a `$event.*` template.

`entry.delete` is deliberately NOT offered here.
"""

import uuid

from ..matcher import interpolate
from .base import AutomationActionError, register_action

# Status op → the status the transition moves the entry to. The specific event (published/archived/…)
# is derived by EntryService from the entry's prior status, so these stay declarative.
ENTRY_OPS: dict[str, str] = {
    "publish": "published",
    "unpublish": "draft",
    "archive": "archived",
    "restore": "draft",
}

# Collection-membership ops → the EntryService method that performs (and emits) them.
COLLECTION_OPS: dict[str, str] = {
    "add_to_collection": "add_to_collection",
    "remove_from_collection": "remove_from_collection",
}

# Merge a (templated) dict into the entry's metadata_json — e.g. record an external system's id
# (`buttondown_subscriber_id: $steps.subscribe.output.body.id`) so later events can find the entry.
METADATA_OPS = ("set_metadata",)

# Merge a (templated) dict into the entry's schema fields (data_json). Fields read data_json before
# metadata_json, so a schema field (one the type declares) can only be changed here, not by
# set_metadata. The entry type's schema validates the result (an unknown select option fails).
DATA_OPS = ("set_data",)

ALL_OPS = (*ENTRY_OPS, *COLLECTION_OPS, *METADATA_OPS, *DATA_OPS)


def _typed_like_schema(patch: dict, entry_type) -> dict:
    """Convert typed-in text to the field's type — the workflow editor sends every value as text, so
    a checkbox set to `true` arrives as "true" and a number as "45". Only text bound for a boolean or
    number field is touched; anything that won't convert is left for schema validation to reject."""
    from marvin.schemas.platform.entry_type_schema import BooleanFieldSchema, NumberFieldSchema
    from marvin.services.entries.completeness import parse_schema

    from ..matcher import as_bool, as_number

    schema = parse_schema(getattr(entry_type, "schema_json", None))
    if schema is None:
        return patch
    out = dict(patch)
    for key, value in patch.items():
        if not isinstance(value, str):
            continue
        field = schema.get_field(key)
        if isinstance(field, BooleanFieldSchema):
            converted = as_bool(value)
        elif isinstance(field, NumberFieldSchema):
            converted = as_number(value)
        else:
            continue
        if converted is not None:
            out[key] = converted
    return out


# `if_none` on an entity_query step: what no match means. Unset / "fail" fails the step; "skip" ends it
# quietly — for events that may concern no entry here (a newsletter reader who signed up elsewhere).
# More than one match always fails: acting on a guess is worse than stopping.
IF_NONE_SKIP = "skip"


def _resolve_target(session, group_id, action: dict, context: dict):
    """Resolve which entry to act on: by query, by slug, or an id (default: the triggering entry).
    None only when an entity_query with `if_none: skip` matched nothing."""
    from ..runner import _resolve_entry_id_by_slug

    # `entity_query`: find exactly one entry with the target-selector vocabulary, resolved at
    # action time so it can use an earlier step's output (`metadata: {ext_id: $steps.lookup.output.body.id}`)
    # — which a top-level `target` cannot, since targets resolve before any step runs.
    if action.get("entity_query"):
        from marvin.services.entries.query import run as run_entry_query

        query = interpolate(action["entity_query"], context)
        rows = run_entry_query(session, group_id, query if isinstance(query, dict) else {}, limit=2).rows
        if not rows and action.get("if_none") == IF_NONE_SKIP:
            return None
        if len(rows) != 1:
            raise AutomationActionError(f"entry action entity_query matched {len(rows)} entries (need exactly 1): {query}")
        return rows[0].id

    slug = interpolate(action.get("entity_slug"), context) if action.get("entity_slug") else None
    if slug:
        return _resolve_entry_id_by_slug(session, group_id, str(slug))

    raw = interpolate(action.get("entity_id", "$event.entry_id"), context)
    if not raw:
        raise AutomationActionError(
            "entry action has no target entry — set entity_slug (e.g. $event.payload.entry_slug), add a Run-on target, or trigger on an entry event"
        )
    try:
        return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
    except (ValueError, TypeError) as e:
        raise AutomationActionError("entry action needs a valid entry id or slug") from e


def _resolve_collection_ref(action: dict, context: dict):
    """The collection a membership op targets — collection_slug (preferred, may be a template) or id."""
    ref = interpolate(action.get("collection_slug"), context) if action.get("collection_slug") else None
    if not ref:
        ref = interpolate(action.get("collection_id"), context) if action.get("collection_id") else None
    if not ref:
        raise AutomationActionError(
            "collection action needs a target collection — set collection_slug (e.g. 'featured' or $event.payload.collection_slug)"
        )
    return str(ref)


@register_action("entry")
def run_entry_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from marvin.services.entries import EntryService

    from ..authz import ENTRY_ACTION_MIN_ROLE, ROLE_OWNER, require_role

    op = action.get("op")
    if op not in ALL_OPS:
        raise AutomationActionError(f"unknown entry action op '{op}' (expected: {', '.join(ALL_OPS)})")

    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, ENTRY_ACTION_MIN_ROLE, f"entry action '{op}'")

    entity_id = _resolve_target(session, group_id, action, context)
    if entity_id is None:
        # A successful no-op: the run is green and the step's output says why nothing happened.
        return {"op": op, "skipped": True, "reason": "no matching entry", "query": interpolate(action["entity_query"], context)}
    # Emitted events chain at depth+1 so the loop-guard bounds any cascade.
    depth = int(context.get("depth", 0)) + 1

    # ── Collection membership ──────────────────────────────────────────────────
    if op in COLLECTION_OPS:
        collection_ref = _resolve_collection_ref(action, context)
        if dry_run:  # resolve target + collection, but don't construct the service or mutate
            return {"dry_run": True, "kind": "entry", "op": op, "entity_id": str(entity_id), "collection": collection_ref}
        svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
        result = getattr(svc, COLLECTION_OPS[op])(entity_id, collection_ref, reaction_depth=depth)
        if result is None:
            raise AutomationActionError(f"entry {entity_id} or collection '{collection_ref}' not found in this workspace")
        return {"entry_id": str(entity_id), "op": op, "collection": collection_ref, "result": result}

    # ── Metadata merge ─────────────────────────────────────────────────────────
    if op in METADATA_OPS:
        patch = interpolate(action.get("metadata") or {}, context)
        if not isinstance(patch, dict) or not patch:
            raise AutomationActionError("entry set_metadata needs a non-empty `metadata` object")
        # A template that resolved to nothing must not overwrite a real value with null.
        patch = {k: v for k, v in patch.items() if v is not None and v != ""}
        if not patch:
            raise AutomationActionError("entry set_metadata: every metadata value resolved to empty")
        if dry_run:
            return {"dry_run": True, "kind": "entry", "op": op, "entity_id": str(entity_id), "would_merge": patch}
        from marvin.db.models.platform.entries import Entries

        orm = session.get(Entries, entity_id)
        if orm is None or orm.group_id != group_id:
            raise AutomationActionError(f"entry {entity_id} not found in this workspace")
        merged = {**(orm.metadata_json or {}), **patch}
        svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
        if svc.update(entity_id, {"metadata_json": merged}, reaction_depth=depth) is None:
            raise AutomationActionError(f"entry {entity_id} not found in this workspace")
        return {"entry_id": str(entity_id), "op": op, "merged": patch}

    # ── Schema-field merge ─────────────────────────────────────────────────────
    if op in DATA_OPS:
        patch = interpolate(action.get("data") or {}, context)
        if not isinstance(patch, dict) or not patch:
            raise AutomationActionError("entry set_data needs a non-empty `data` object")
        patch = {k: v for k, v in patch.items() if v is not None and v != ""}
        if not patch:
            raise AutomationActionError("entry set_data: every data value resolved to empty")
        if dry_run:
            return {"dry_run": True, "kind": "entry", "op": op, "entity_id": str(entity_id), "would_merge": patch}
        from fastapi import HTTPException

        from marvin.db.models.platform.entries import Entries

        orm = session.get(Entries, entity_id)
        if orm is None or orm.group_id != group_id:
            raise AutomationActionError(f"entry {entity_id} not found in this workspace")
        merged = {**(orm.data_json or {}), **_typed_like_schema(patch, getattr(orm, "entry_type", None))}
        svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
        try:
            updated = svc.update(entity_id, {"data_json": merged}, reaction_depth=depth)
        except HTTPException as e:  # schema validation rejected the merged fields
            raise AutomationActionError(f"entry set_data rejected: {e.detail}") from e
        if updated is None:
            raise AutomationActionError(f"entry {entity_id} not found in this workspace")
        return {"entry_id": str(entity_id), "op": op, "merged": patch}

    # ── Status transition ──────────────────────────────────────────────────────
    if dry_run:
        return {"dry_run": True, "kind": "entry", "op": op, "entity_id": str(entity_id), "would_set_status": ENTRY_OPS[op]}
    from fastapi import HTTPException

    svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
    try:
        entry = svc.set_status(entity_id, ENTRY_OPS[op], reaction_depth=depth)
    except HTTPException as e:  # the publish gate refused: required fields missing, expiry passed, …
        detail = e.detail if isinstance(e.detail, dict) else {}
        reason = "; ".join(detail.get("issues") or []) or detail.get("message") or e.detail
        raise AutomationActionError(f"entry {op} refused: {reason}") from e
    if entry is None:
        raise AutomationActionError(f"entry {entity_id} not found in this workspace")
    return {"entry_id": str(entity_id), "op": op, "status": ENTRY_OPS[op]}
