"""`entry` action — act on an entry. No AI.

Two families, both through EntryService so the right events fire and chains stay reliable:
  * **status** — publish / unpublish / archive / trash / restore (emits entry_published /
    entry_unpublished / entry_archived / entry_trashed / entry_restored). `restore` brings a trashed
    entry back to the status it had (a published one as a draft), and an archived one to draft.
  * **collection membership** — add_to_collection / remove_from_collection (emits
    entry_added_to_collection / entry_removed_from_collection), idempotent.
  * **field writes** — set_metadata (merge into metadata_json) and set_data (merge into the schema
    fields in data_json, validated against the entry type — e.g. a select field's new option).
  * **review** — request_review moves the entry to Needs review and, given a `reason`, adds it to
    `metadata_json.review_reasons` (shown with the entry, beside a form submission's own reasons).

It targets the triggering entry (`$event.entry_id`) by default, an entry by slug (`entity_slug`), or
an explicit id — so it pairs with the target selector to act on a whole query: "add all drafts
matching X to the Featured collection" is a `target` selecting drafts + an add_to_collection action,
since each matched entry is bound to `$event.entry_id` for its fan-out row. Collection ops take a
`collection_slug` (or `collection_id`), which may itself be a `$event.*` template.

`entry.delete` is deliberately NOT offered here, and neither is emptying the Trash: `trash` is reversible,
permanent deletion stays a person's action. "Move every X to the Trash" is a `target` + a `trash` action;
entries already in the Trash are skipped (a no-op, nothing emitted).

`trash` and `restore` also act on an asset or a resource, with `entity_type: asset | resource` (services/trash.py:
`asset_trashed` / `asset_restored`, `resource_trashed` / `resource_restored`). The target is `entity_slug` or
`entity_id` (default: the current item, `$event.asset_id` / `$event.resource_id` — the triggering one, or each
row of an asset/resource target). Left unset, `entity_type` follows the run's subject (`$event.entity_type`): on an
asset target or an asset event a bare `trash` trashes the asset. An asset or resource already where the op would
put it is skipped. No other op takes an entity_type.
"""

import re
import uuid

from ..matcher import interpolate
from .base import AutomationActionError, register_action

_STEP_REF = re.compile(r"\$\{steps\.[^}]+\}")


def _previewed(raw, value, dry_run: bool):
    """In a dry run, a value read from a step that only previewed (no answer asked, no image made) is empty: show where
    it comes from (‹${steps.page.output.asset.slug}›) instead of failing on it. A real run leaves it as it resolved."""
    if dry_run and value in (None, "") and isinstance(raw, str) and _STEP_REF.search(raw):
        return f"‹{raw.strip()}›"
    return value


def _resolved_map(action: dict, key: str, context: dict, dry_run: bool) -> dict:
    raw = action.get(key) or {}
    resolved = _json_ready(interpolate(raw, context))
    if not isinstance(resolved, dict):
        return resolved
    return {k: _previewed(raw.get(k) if isinstance(raw, dict) else None, v, dry_run) for k, v in resolved.items()}


# Status op → the status the transition moves the entry to. The specific event (published/archived/…)
# is derived by EntryService from the entry's prior status, so these stay declarative.
ENTRY_OPS: dict[str, str] = {
    "publish": "published",
    "unpublish": "draft",
    "archive": "archived",
    "trash": "trashed",
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

# Send the entry to the review queue, saying why — e.g. a workflow's on_failure steps flagging a
# signup an integration refused. Its own family because it may write a reason with the status.
REVIEW_OPS = ("request_review",)
REVIEW_STATUS = "needs_review"
REVIEW_REASONS_KEY = "review_reasons"

# Make a new entry (`entry_type`, `title`, `data`, `metadata`, `status`). Only inbox or draft: publishing goes through
# a following publish step, which checks the type's completeness rules. The run + step key in CREATED_KEY means the same
# event handled twice finds the entry it already made instead of making a second.
CREATE_OPS = ("create",)
CREATE_STATUSES = ("inbox", "draft")
CREATED_KEY = "automation_created"
# Attach an asset (by id or slug — a step's generated picture, say) to the entry in a role. Its own op so a run can
# make a picture, show it at an approval, and attach it only once a person says yes.
ATTACH_OPS = ("attach_asset",)

ALL_OPS = (*ENTRY_OPS, *COLLECTION_OPS, *METADATA_OPS, *DATA_OPS, *REVIEW_OPS, *CREATE_OPS, *ATTACH_OPS)

# What each op sends (through EntryService), from the entry's usual starting point: every write sends
# entry_updated, a status op its transition too. The Events hub lists a workflow with these steps as a
# sender (services/events/connections.py). A different starting status can add one (archiving a
# published entry also sends entry_unpublished); test_event_connections runs each op to keep this honest.
OP_SENDS: dict[str, tuple[str, ...]] = {
    "publish": ("entry_updated", "entry_published"),
    "unpublish": ("entry_updated", "entry_unpublished"),
    "archive": ("entry_updated", "entry_archived"),
    "trash": ("entry_updated", "entry_trashed"),
    "restore": ("entry_updated", "entry_restored"),
    "add_to_collection": ("entry_added_to_collection",),
    "remove_from_collection": ("entry_removed_from_collection",),
    "set_metadata": ("entry_updated",),
    "set_data": ("entry_updated",),
    "request_review": ("entry_updated",),
    "create": ("entry_created",),
}

# Ops that also act on an asset or a resource (`entity_type`), and what each sends there — one event, no
# entry_updated. Checked the same way as OP_SENDS (test_event_connections).
ITEM_TYPES = ("asset", "resource")
ITEM_OPS = ("trash", "restore")
ITEM_OP_SENDS: dict[tuple[str, str], tuple[str, ...]] = {
    (kind, op): (f"{kind}_{'trashed' if op == 'trash' else 'restored'}",) for kind in ITEM_TYPES for op in ITEM_OPS
}


def subject_kind(context: dict) -> str | None:
    """The asset or resource a run is about (`$event.entity_type`: an asset/resource event's, or the current row of an
    asset/resource target) — what a step without an entity_type acts on. None when the subject is an entry or nothing."""
    kind = (context.get("event") or {}).get("entity_type")
    return kind if kind in ITEM_TYPES else None


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


def _json_ready(value):
    """A templated patch as JSON can hold it: a whole-value template keeps its type, and the event context carries
    UUIDs (`${event.user_id}`) and datetimes (`${event.publish_at}`) that a JSON column can't store as they are."""
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)


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

    if op in CREATE_OPS:
        return _create_entry(session, group_id, action, context, user_id=user_id, dry_run=dry_run)
    entity_type = action.get("entity_type") or (subject_kind(context) if op in ITEM_OPS else None) or "entry"
    if entity_type != "entry":
        return _run_item_op(session, group_id, entity_type, op, action, context, user_id=user_id, dry_run=dry_run)

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

    # ── Metadata / schema-field merge ─────────────────────────────────────────
    if op in METADATA_OPS or op in DATA_OPS:
        key = "metadata" if op in METADATA_OPS else "data"
        return _merge(session, group_id, entity_id, op, key, action, context, user_id=user_id, depth=depth, dry_run=dry_run)

    if op in ATTACH_OPS:
        return _attach_asset(session, group_id, entity_id, action, context, user_id=user_id, depth=depth, dry_run=dry_run)
    if op in REVIEW_OPS:
        return _request_review(session, group_id, entity_id, action, context, user_id=user_id, depth=depth, dry_run=dry_run)

    # ── Status transition ──────────────────────────────────────────────────────
    if dry_run:
        return {
            "dry_run": True,
            "kind": "entry",
            "op": op,
            "entity_id": str(entity_id),
            "would_set_status": _would_set_status(session, op, entity_id),
        }
    return _set_status(session, group_id, entity_id, op, user_id=user_id, depth=depth)


def _create_key(context: dict) -> str | None:
    """This step of this run: the event's correlation id, the workflow, the target row and the step. None without a
    correlation id (nothing to tell two deliveries of one event apart by)."""
    from marvin.services.event_bus_service.correlation import current_correlation_id

    correlation = (context.get("event") or {}).get("correlation_id") or current_correlation_id.get()
    step = context.get("_step") or {}
    if not correlation or not step:
        return None
    return f"{correlation}:{step.get('workflow')}:{step.get('target')}:{step.get('index')}{':on_failure' if step.get('on_failure') else ''}"


def _entry_type_by_slug(session, group_id, slug: str):
    from marvin.db.models.platform.entry_types import EntryTypes

    rows = session.query(EntryTypes).filter(EntryTypes.slug == slug, (EntryTypes.group_id == group_id) | (EntryTypes.group_id.is_(None))).all()
    return next((t for t in rows if t.group_id == group_id), rows[0] if rows else None)  # the workspace's own first


def _merge(session, group_id, entity_id, op: str, key: str, action: dict, context: dict, *, user_id, depth: int, dry_run: bool) -> dict:
    """set_metadata / set_data: merge the step's values into the entry's metadata or its type's fields. A value that
    resolved to nothing never overwrites a real one; a merge that changes nothing saves nothing (no "last updated" bump,
    no entry_updated), so a weekly check that finds the same answer leaves the entry alone."""
    from fastapi import HTTPException

    from marvin.db.models.platform.entries import Entries
    from marvin.services.entries import EntryService

    patch = _resolved_map(action, key, context, dry_run)
    if not isinstance(patch, dict) or not patch:
        raise AutomationActionError(f"entry {op} needs a non-empty `{key}` object")
    patch = {k: v for k, v in patch.items() if v is not None and v != ""}
    if not patch:
        raise AutomationActionError(f"entry {op}: every {key} value resolved to empty")
    if dry_run:
        return {"dry_run": True, "kind": "entry", "op": op, "entity_id": str(entity_id), "would_merge": patch}
    orm = session.get(Entries, entity_id)
    if orm is None or orm.group_id != group_id:
        raise AutomationActionError(f"entry {entity_id} not found in this workspace")
    column = "metadata_json" if key == "metadata" else "data_json"
    current = getattr(orm, column) or {}
    merged = {**current, **(patch if key == "metadata" else _typed_like_schema(patch, getattr(orm, "entry_type", None)))}
    if merged == current:
        return {"entry_id": str(entity_id), "op": op, "merged": patch, "unchanged": True}
    svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
    try:
        updated = svc.update(entity_id, {column: merged}, reaction_depth=depth)
    except HTTPException as e:  # the type's schema refused the merged fields
        raise AutomationActionError(f"entry {op} rejected: {e.detail}") from e
    if updated is None:
        raise AutomationActionError(f"entry {entity_id} not found in this workspace")
    return {"entry_id": str(entity_id), "op": op, "merged": patch}


def _create_entry(session, group_id, action: dict, context: dict, *, user_id, dry_run: bool) -> dict:
    """Make a new entry: typed and validated against its entry type's schema, `entry_created` sent at depth+1. The same
    step of the same run (an event handled twice) returns the entry it made before (`created: false`)."""
    from fastapi import HTTPException

    from marvin.db.models.platform.entries import Entries
    from marvin.repos.repository_factory import AllRepositories
    from marvin.services.entries import EntryService

    type_slug = str(interpolate(action.get("entry_type") or "", context) or "").strip()
    entry_type = _entry_type_by_slug(session, group_id, type_slug)
    if entry_type is None:
        raise AutomationActionError(f"entry create: no entry type “{type_slug}” in this workspace")
    title = str(_previewed(action.get("title"), interpolate(action.get("title") or "", context), dry_run) or "").strip()
    if not title:
        raise AutomationActionError("entry create: the title resolved to empty")
    status = action.get("status") or "draft"
    if status not in CREATE_STATUSES:
        raise AutomationActionError(f"entry create: status must be {' or '.join(CREATE_STATUSES)} (publish with a following step)")
    data = _resolved_map(action, "data", context, dry_run)
    data = _typed_like_schema({k: v for k, v in (data or {}).items() if v is not None and v != ""}, entry_type)
    metadata = _resolved_map(action, "metadata", context, dry_run)
    metadata = {k: v for k, v in (metadata or {}).items() if v is not None and v != ""}
    key = _create_key(context)
    if key:
        metadata[CREATED_KEY] = key
        made = session.query(Entries).filter(Entries.group_id == group_id, Entries.metadata_json[CREATED_KEY].as_string() == key).first()
        if made is not None:
            return {"op": "create", "entry_id": str(made.id), "slug": made.slug, "created": False}
    if dry_run:
        try:
            AllRepositories(session, group_id=group_id).entries._validate_content(entry_type.id, data)
        except HTTPException as e:
            raise AutomationActionError(f"entry create rejected: {e.detail}") from e
        return {"dry_run": True, "kind": "entry", "op": "create", "entry_type": entry_type.slug, "title": title, "status": status, "data": data}
    svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
    payload = {
        "entry_type_id": entry_type.id,
        "title": title,
        "status": status,
        "data_json": data,
        "metadata_json": metadata or None,
        "created_by": user_id,
    }
    try:
        entry = svc.create(payload, reaction_depth=int(context.get("depth", 0)) + 1)
    except HTTPException as e:  # the type's schema refused the fields
        session.rollback()
        raise AutomationActionError(f"entry create rejected: {e.detail}") from e
    return {"op": "create", "entry_id": str(entry.id), "slug": entry.slug, "created": True, "status": status}


def _set_status(session, group_id, entity_id, op: str, *, user_id, depth: int) -> dict:
    """Run a status op. `trash` on an entry already in the Trash is skipped (nothing emitted); `restore` on a
    trashed entry returns it to the status it had before (a published one as a draft)."""
    from fastapi import HTTPException

    from marvin.services.entries import EntryService

    svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
    trashed = op in ("trash", "restore") and _is_trashed(session, group_id, entity_id)
    if op == "trash" and trashed:
        return {"entry_id": str(entity_id), "op": op, "skipped": True, "reason": "already in the Trash"}
    try:
        if op == "trash":
            entry = svc.trash(entity_id, reaction_depth=depth)
        elif op == "restore" and trashed:
            entry = svc.restore_from_trash(entity_id, reaction_depth=depth)
        else:
            entry = svc.set_status(entity_id, ENTRY_OPS[op], reaction_depth=depth)
    except HTTPException as e:  # the publish gate refused: required fields missing, expiry passed, …
        detail = e.detail if isinstance(e.detail, dict) else {}
        reason = "; ".join(detail.get("issues") or []) or detail.get("message") or e.detail
        raise AutomationActionError(f"entry {op} refused: {reason}") from e
    if entry is None:
        raise AutomationActionError(f"entry {entity_id} not found in this workspace")
    return {"entry_id": str(entity_id), "op": op, "status": entry.status if trashed else ENTRY_OPS[op]}


def _would_set_status(session, op: str, entity_id) -> str:
    """The status a status op moves the entry to — for `restore` on a trashed entry, the one it had."""
    if op == "restore":
        from marvin.db.models.platform.entries import Entries
        from marvin.services.entries.entry_service import restore_status

        orm = session.get(Entries, entity_id)
        if orm is not None and orm.status == "trashed":
            return restore_status(orm)
    return ENTRY_OPS[op]


def _is_trashed(session, group_id, entity_id) -> bool:
    from marvin.db.models.platform.entries import Entries

    orm = session.get(Entries, entity_id)
    return orm is not None and orm.group_id == group_id and orm.status == "trashed"


def _request_review(session, group_id, entity_id, action: dict, context: dict, *, user_id, depth: int, dry_run: bool) -> dict:
    """Move the entry to Needs review, adding the (templated) `reason` to its review reasons — once:
    the same reason twice (a re-run) is not listed twice."""
    reason = interpolate(action.get("reason"), context) if action.get("reason") else None
    reason = str(reason).strip() if reason not in (None, "") else ""
    if dry_run:
        preview = {"dry_run": True, "kind": "entry", "op": "request_review", "entity_id": str(entity_id)}
        return {**preview, "would_set_status": REVIEW_STATUS, "reason": reason}
    request_review(session, group_id, entity_id, reason=reason, user_id=user_id, depth=depth)
    return {"entry_id": str(entity_id), "op": "request_review", "status": REVIEW_STATUS, "reason": reason or None}


def request_review(session, group_id, entity_id, *, reason: str = "", metadata: dict | None = None, user_id=None, depth: int = 0) -> None:
    """Move an entry to Needs review in one update (one entry_updated): add ``reason`` to its review
    reasons (not twice) and merge ``metadata`` (top-level keys) into its metadata_json. Also how an
    integration's error policy sends an entry to review (`services/integrations/errors.py`)."""
    from marvin.services.entries import EntryService

    svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
    if not reason and not metadata:
        entry = svc.set_status(entity_id, REVIEW_STATUS, reaction_depth=depth)
    else:
        from marvin.db.models.platform.entries import Entries

        orm = session.get(Entries, entity_id)
        if orm is None or orm.group_id != group_id:
            raise AutomationActionError(f"entry {entity_id} not found in this workspace")
        merged = {**(orm.metadata_json or {}), **(metadata or {})}
        if reason:
            reasons = [r for r in (merged.get(REVIEW_REASONS_KEY) or []) if isinstance(r, str)]
            merged[REVIEW_REASONS_KEY] = reasons if reason in reasons else [*reasons, reason]
        # One update, so the status change and its reason land together (one entry_updated).
        entry = svc.update(entity_id, {"status": REVIEW_STATUS, "metadata_json": merged}, reaction_depth=depth)
    if entry is None:
        raise AutomationActionError(f"entry {entity_id} not found in this workspace")


def _run_item_op(session, group_id, kind: str, op: str, action: dict, context: dict, *, user_id, dry_run: bool) -> dict:
    """`trash` / `restore` on an asset or resource (services/trash.py). Already where the op would put it →
    skipped, nothing emitted."""
    from marvin.services import trash

    if kind not in ITEM_TYPES:
        raise AutomationActionError(f"unknown entity_type '{kind}' (expected: entry, {', '.join(ITEM_TYPES)})")
    if (kind, op) not in ITEM_OP_SENDS:
        raise AutomationActionError(f"entry action op '{op}' does not take entity_type '{kind}' (only trash and restore do)")
    if action.get("entity_query"):
        raise AutomationActionError(f"entity_query finds entries only — target the {kind} by entity_slug or entity_id")
    row = _resolve_item(session, group_id, kind, action, context)
    key = f"{kind}_id"
    if (op == "trash") == trash.is_trashed(row):
        reason = "already in the Trash" if op == "trash" else "not in the Trash"
        return {key: str(row.id), "op": op, "skipped": True, "reason": reason}
    if dry_run:
        return {"dry_run": True, "kind": "entry", "entity_type": kind, "op": op, "entity_id": str(row.id)}
    depth = int(context.get("depth", 0)) + 1
    move = trash.trash if op == "trash" else trash.restore
    move(session, group_id, kind, row.id, actor_id=user_id, reaction_depth=depth)
    return {key: str(row.id), "op": op, "trashed": op == "trash"}


def _resolve_item(session, group_id, kind: str, action: dict, context: dict):
    """The asset or resource an item op targets: by slug, or an id (default: the triggering one)."""
    from marvin.services import trash

    model = trash.model(kind)
    slug = interpolate(action.get("entity_slug"), context) if action.get("entity_slug") else None
    if slug:
        row = session.query(model).filter(model.group_id == group_id, model.slug == str(slug)).first()
        if row is None:
            raise AutomationActionError(f"no {kind} with slug '{slug}' in this workspace")
        return row
    raw = interpolate(action.get("entity_id", f"$event.{kind}_id"), context)
    if not raw:
        raise AutomationActionError(f"entry action on a {kind} has no target — set entity_slug or entity_id, or trigger on an {kind} event")
    try:
        row = session.get(model, raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw)))
    except (ValueError, TypeError) as e:
        raise AutomationActionError(f"entry action needs a valid {kind} id or slug") from e
    if row is None or row.group_id != group_id:
        raise AutomationActionError(f"{kind} {raw} not found in this workspace")
    return row


def _attach_asset(session, group_id, entity_id, action: dict, context: dict, *, user_id, depth: int, dry_run: bool) -> dict:
    """`{"kind": "entry", "op": "attach_asset", "asset": "${steps.cover.output.images.0.asset.id}", "role": "cover"}`:
    the asset (id or slug; templates allowed) linked to the entry in `role`. Idempotent: an asset already in that
    role is left as it is."""
    from marvin.services.entries import EntryService

    raw = action.get("asset")
    ref = str(interpolate(raw, context) or "").strip() if raw not in (None, "") else ""
    if not ref:
        raise AutomationActionError("attach_asset needs `asset`: the asset's id or slug (a template such as ${steps.cover.output.images.0.asset.id})")
    role = str(interpolate(action.get("role"), context) or "").strip() or None if action.get("role") else None
    if dry_run:
        return {"dry_run": True, "kind": "entry", "op": "attach_asset", "entity_id": str(entity_id), "asset": ref, "role": role}
    svc = EntryService(session, group_id, actor_id=user_id, integration_id="automation")
    result = svc.attach_asset(entity_id, ref, role=role, reaction_depth=depth)
    if result is None:
        raise AutomationActionError(f"entry {entity_id} or asset '{ref}' not found in this workspace")
    return {"entry_id": str(entity_id), "op": "attach_asset", "asset": ref, "role": role, "result": result}
