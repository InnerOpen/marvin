"""One entry query for every surface that finds entries matching a description.

The agent's `find_entries`, a workflow's "Run on a query of entries" (and an entry step's
`entity_query`) and the agent's bulk actions all used to build their own query, each knowing a
different subset of filters. They now share this one, so a filter added here works everywhere.

A spec is a plain dict (all keys optional, unknown keys ignored):

- ``entry_type`` / ``entry_types`` — type slug(s); `bench_note` and `bench-note` both match. Entries of an internal type
  (``capabilities.listed: false``, services/entry_listing.py) are found only when the spec names their type (or the
  entries themselves with ``entries``).
- ``status`` / ``statuses`` — the PUBLISH status (inbox, draft, needs_review, approved, published,
  archived, trashed). A value that isn't one (usually a field's value) yields a note instead of a silent 0.
  Entries in the Trash are left out unless ``trashed`` is asked for by name — so a workflow target
  "all entries" + a `trash` action never re-touches them, and agents don't find deleted entries.
- ``text`` / ``query`` — title or slug contains (case-insensitive).
- ``tags`` — any of these tags (slug or name). ``collection`` / ``collections`` — in any of these (slug or name).
- ``has_images`` / ``has_assets`` / ``has_resources``.
- ``entries`` — exactly these entries (ids or slugs; one or a list): the entry a field names (``${entry.data.project}``).
- ``asset`` / ``resource`` — linked to this asset / resource (id or slug): the entries that use a picture or a supplier.
- ``referenced_by`` / ``not_referenced_by`` — ``{entry_type, field, fields?}``: an entry of that type (out of the Trash, narrowed by
  ``fields``) holds this one's slug in its ``field`` (a ref field), or none does: the beats with lines, the actors cast in a story.
- ``fields`` / ``data`` — exact match on the entry type's own fields ``{key: value}``; ``metadata`` the same on
  metadata. Typed-in text matches checkbox/number values. An empty value matches nothing.
- ``where`` — ``[{"field": key, "op": op, "value": v}]``; ``field`` is a field key, or ``metadata.<key>``.
  ``op``: eq, neq, in, contains, exists, missing, gt, gte, lt, lte. Comparisons read number-like text
  (`"$1,170"` → 1170), so they work on fields stored as text.
- ``created_after``/``created_before``, ``updated_after``/``updated_before``, ``published_after``/``published_before``
  — ISO dates or datetimes (UTC), or relative to now: ``-7d``, ``-12h``, ``-2w``, ``now``, ``today``.
- ``sort`` — ``{"by": "title"|"created_at"|"updated_at"|"published_at"|"position"|<field key>, "direction": "asc"|"desc",
  "then"?: <field key>|"created_at"|...}``;
  a field sorts numerically when its values are number-like, else as text read naturally (numbers inside it as numbers:
  "beat-1001" before "beat-10001"); empty values sort last. ``then`` orders the entries alike in ``by`` by a second field (a
  story's lines: ``{"by": "beat", "then": "order"}``) or by one of its own columns (a story's takes: ``{"by": "line", "then":
  "created_at"}``, line by line in the order recorded). ``position`` is the
  order of the one ``collection`` the spec names, as the site shows it (its order, then newest published).
- ``group_by`` — a field key, or ``publish_status`` / ``entry_type``: counts per value over the whole match.

In ``where``, ``sort`` and ``group_by`` a bare key is always the entry type's own field (a type may well
have its own ``status`` field); ``publish_status`` and ``entry_type`` name the entry's built-ins.

Everything that SQL can express portably runs in SQL. ``where``, sorting by a field and ``group_by``
need per-row reading (number-like text, JSON values), so they run over the SQL-filtered rows in Python,
bounded by ``SCAN_CAP`` — and the result says when that bound was hit.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

SCAN_CAP = 5000
"""Most rows read into memory for where / sort-by-field / group_by; a workspace bigger than this gets `scan_capped`."""

SPEC_KEYS = (
    *("entry_type", "entry_types", "status", "statuses", "text", "query", "tags", "collection", "collections"),
    *("has_images", "has_assets", "has_resources", "entries", "asset", "resource", "referenced_by", "not_referenced_by"),
    *("fields", "data", "metadata", "where", "sort", "group_by"),
    *(f"{name}_{edge}" for name in ("created", "updated", "published") for edge in ("after", "before")),
)
"""Every key a spec understands. Unknown keys are ignored, so a caller that must never widen a selection (the
agent's trash_entries `match`) rejects any key not here instead."""

WHERE_OPS = ("eq", "neq", "in", "contains", "exists", "missing", "gt", "gte", "lt", "lte")
COLUMN_SORTS = ("title", "created_at", "updated_at", "published_at")
POSITION = "position"  # a collection's own order (sort.by)

# What each of SPEC_KEYS means, in a line — the agent's workflow authoring guide lists these for a workflow's
# `target.query` (test_entry_query keeps both matching what `build` / `run` read).
SPEC_KEY_NOTES: dict[str, str] = {
    "entry_type": "entry type slug (`entry_types`: a list)",
    "entry_types": "entry type slugs, any of",
    "status": "publish status (`statuses`: a list); the Trash is left out unless `trashed` is named",
    "statuses": "publish statuses, any of",
    "text": "title or slug contains (same as `query`)",
    "query": "same as `text`",
    "tags": "has any of these tags (slug or name)",
    "collection": "in this collection (slug or name; `collections`: a list)",
    "collections": "in any of these collections",
    "has_images": "true: has an image attached; false: has none",
    "has_assets": "true: has any asset attached; false: has none",
    "has_resources": "true: has a resource linked; false: has none",
    "entries": "exactly these (ids or slugs, a list or comma-separated text), e.g. ${entry.data.project}",
    "asset": "uses this asset (id or slug)",
    "resource": "has this resource linked (id or slug)",
    "referenced_by": "{entry_type, field, fields?}: an entry of that type (narrowed by fields) holds this one's slug in its field",
    "not_referenced_by": "the opposite of referenced_by: no such entry holds this one's slug",
    "fields": "exact match on the entry type's own fields, {field_key: value}",
    "data": "same as `fields`",
    "metadata": "exact match on metadata_json keys, {key: value}",
    "where": f"comparisons [{{field, op, value}}]; field = a field key or metadata.<key>; op: {', '.join(WHERE_OPS)}",
    "created_after": "ISO date/datetime (UTC) or relative to now: -7d, -12h, -2w, now, today; also created_before",
    "created_before": "a date, as created_after",
    "updated_after": "a date, as created_after; also updated_before",
    "updated_before": "a date, as created_after",
    "published_after": "a date, as created_after; also published_before",
    "published_before": "a date, as created_after",
    "sort": (
        f"{{by: {' | '.join(COLUMN_SORTS)} | position | <field key>, direction: asc | desc, then?: <field key> | created_at}}; "
        "position: the collection's order; then: a second field (or column) for ties"
    ),
    "group_by": "a field key, publish_status or entry_type: counts per value",
}
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class EntryQueryResult:
    rows: list
    total: int
    note: str | None = None
    groups: dict[str, int] | None = None
    scan_capped: bool = False
    unknown_ops: list[str] = field(default_factory=list)


def _yes_no(value) -> bool | None:
    """A has_* flag: True / False (also the words a template renders, "true" / "false"), else None (no filter)."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower() if value is not None else ""
    return True if text == "true" else False if text == "false" else None


def number_like(value: Any) -> float | None:
    """A number read the way a person reads it: 45, "45", "$1,170", "12.5 in" → float; else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    match = _NUMBER.search(str(value).replace(",", ""))
    return float(match.group()) if match else None


def _as_list(value) -> list[str]:
    if value is None or value == "":
        return []
    items = value if isinstance(value, list | tuple | set) else [value]
    return [str(v).strip() for v in items if str(v).strip()]


RELATIVE = re.compile(r"^(?P<sign>[+-]?)\s*(?P<n>\d+)\s*(?P<unit>h|d|w)$", re.IGNORECASE)
RELATIVE_UNITS = {"h": "hours", "d": "days", "w": "weeks"}


def _when(value, now: datetime | None = None) -> datetime | None:
    """A query's date: an ISO date/datetime (UTC unless it says otherwise), or relative to now — "-7d", "-12h", "-2w"
    (ago; "+3d" is ahead, a bare "30d" means ago), "now", or "today" (midnight UTC). None when it isn't one."""
    if not value:
        return None
    text = str(value).strip()
    now = now or datetime.now(UTC)
    if text.lower() == "now":
        return now
    if text.lower() == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if m := RELATIVE.match(text):
        delta = timedelta(**{RELATIVE_UNITS[m["unit"].lower()]: int(m["n"])})
        return now + delta if m["sign"] == "+" else now - delta
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build(session, group_id, spec: dict | None, *, exclude_types: tuple[str, ...] = ()):
    """The SQL part of a spec: (query over Entries, note). The note explains a filter that can't match. ``exclude_types``
    (entry type slugs) are never matched, however the spec asks for them: the agent tools keep Playbooks out this way."""
    import sqlalchemy as sa

    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.db.models.platform.entry_resources import EntryResources
    from marvin.db.models.platform.entry_tags import EntryTags
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.db.models.platform.resources import Resources
    from marvin.schemas.platform.entries import ENTRY_STATUSES
    from marvin.services.automation.selector import json_field_equals

    spec = spec or {}
    q = session.query(Entries).filter(Entries.group_id == group_id)
    nothing = q.filter(sa.false())
    dialect = session.get_bind().dialect.name

    types = _as_list(spec.get("entry_type")) + _as_list(spec.get("entry_types"))
    if types:
        spellings = {s for t in types for s in (t.lower(), t.lower().replace("_", "-"), t.lower().replace("-", "_"))}
        type_ids = session.query(EntryTypes.id).filter(EntryTypes.group_id == group_id, EntryTypes.slug.in_(spellings))
        q = q.filter(Entries.entry_type_id.in_(type_ids))

    if exclude_types:
        q = q.filter(
            ~Entries.entry_type_id.in_(session.query(EntryTypes.id).filter(EntryTypes.group_id == group_id, EntryTypes.slug.in_(exclude_types)))
        )

    statuses = _as_list(spec.get("status")) + _as_list(spec.get("statuses"))
    if statuses:
        bad = [s for s in statuses if s not in ENTRY_STATUSES]
        if bad:
            note = (
                f"{', '.join(repr(b) for b in bad)} is not a publish status ({', '.join(sorted(ENTRY_STATUSES))}). "
                f'If it\'s a value of the entry type\'s own field, filter with fields, e.g. {{"<field_key>": "{bad[0]}"}}.'
            )
            return nothing, note
        q = q.filter(Entries.status.in_(statuses))
    if "trashed" not in statuses:
        q = q.filter(Entries.status != "trashed")

    # Entries of an internal type (services/entry_listing.py) are found only by asking for the type, the entries or a
    # collection by name: "all entries", a status or a text search never reach them, so a bulk action can't touch them
    # by accident. A named collection returns what it holds (a smart collection with `listed: unlisted` gathers them).
    collections = _as_list(spec.get("collection")) + _as_list(spec.get("collections"))
    if not types and "entries" not in spec and not collections:
        from marvin.services.entry_listing import only_listed

        q = only_listed(session, group_id, q)

    text = spec.get("text") or spec.get("query")
    if text:
        like = f"%{text}%"
        q = q.filter(Entries.title.ilike(like) | Entries.slug.ilike(like))

    tags = _as_list(spec.get("tags"))
    if tags:
        from marvin.db.models.platform.tags import Tags

        tag_ids = session.query(Tags.id).filter(Tags.group_id == group_id, Tags.slug.in_(tags) | Tags.name.in_(tags))
        if not session.query(tag_ids.exists()).scalar():
            return nothing, f"no such tag(s) in this workspace: {', '.join(tags)}"
        q = q.filter(Entries.id.in_(session.query(EntryTags.entry_id).filter(EntryTags.tag_id.in_(tag_ids))))

    if collections:
        coll_ids = session.query(Collections.id).filter(
            Collections.group_id == group_id, Collections.slug.in_(collections) | Collections.name.in_(collections)
        )
        q = q.filter(Entries.id.in_(session.query(EntryCollections.entry_id).filter(EntryCollections.collection_id.in_(coll_ids))))

    # Attachments in the Trash don't count (their links stay for a restore; services/trash.py).
    asset_links = session.query(EntryAssets.entry_id).join(Assets, Assets.id == EntryAssets.asset_id).filter(Assets.trashed_at.is_(None))
    # true = has one, false = has none (e.g. "Bench Notes without an image"); anything else leaves the filter off.
    images, assets, resources = _yes_no(spec.get("has_images")), _yes_no(spec.get("has_assets")), _yes_no(spec.get("has_resources"))
    image_links = asset_links.filter(Assets.asset_type == "image")
    if images is not None:
        q = q.filter(Entries.id.in_(image_links) if images else Entries.id.notin_(image_links))
    if assets is not None and not (assets and images):  # "has images" already implies "has assets"
        q = q.filter(Entries.id.in_(asset_links) if assets else Entries.id.notin_(asset_links))
    if resources is not None:
        resource_links = session.query(EntryResources.entry_id).join(Resources, Resources.id == EntryResources.resource_id)
        resource_links = resource_links.filter(Resources.trashed_at.is_(None))
        q = q.filter(Entries.id.in_(resource_links) if resources else Entries.id.notin_(resource_links))

    q, note = _linked(session, group_id, q, spec)
    if note:
        return nothing, note

    # An empty/None value matches NOTHING rather than dropping the filter: a template that resolved to
    # nothing must never widen the query to the whole workspace.
    for key_name, column in (("metadata", Entries.metadata_json), ("fields", Entries.data_json), ("data", Entries.data_json)):
        pairs = spec.get(key_name)
        if isinstance(pairs, dict) and pairs:
            for key, value in pairs.items():
                if value is None or value == "":
                    return nothing, f"{key_name}.{key} has no value"
                q = q.filter(json_field_equals(column, str(key), value, dialect))

    for name, column in (("created", Entries.created_at), ("updated", Entries.update_at), ("published", Entries.published_at)):
        after, before = _when(spec.get(f"{name}_after")), _when(spec.get(f"{name}_before"))
        for key, at in ((f"{name}_after", after), (f"{name}_before", before)):
            if spec.get(key) and at is None:  # a date it can't read must not widen the selection
                return nothing, f"{key} is not a date: {spec[key]!r} (an ISO date, or relative like -7d, -12h, -2w, now, today)"
        if after:
            q = q.filter(column >= after)
        if before:
            q = q.filter(column < before)

    return q, None


def _linked(session, group_id, q, spec: dict):
    """entries / asset / resource / referenced_by: what an entry is linked to. A key present with nothing in it (a template that
    resolved to nothing) or naming something that isn't there matches nothing, with a note — never everything."""
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.entry_resources import EntryResources
    from marvin.db.models.platform.resources import Resources

    if "entries" in spec:
        # A list, or text listing them with commas (a field naming a project's people: "ada-lovelace, grace-hopper").
        refs = [part.strip() for r in _as_list(spec["entries"]) for part in str(r).split(",") if part.strip()]
        if not refs:
            return q, "entries has no value"
        q = q.filter(Entries.slug.in_(refs) | Entries.id.in_(_uuids(refs)))
    for key, model, link, fk in (("asset", Assets, EntryAssets, "asset_id"), ("resource", Resources, EntryResources, "resource_id")):
        if key not in spec:
            continue
        ref = str(spec[key] or "").strip()
        if not ref:
            return q, f"{key} has no value"
        found = session.query(model.id).filter(model.group_id == group_id, (model.slug == ref) | model.id.in_(_uuids([ref]))).first()
        if found is None:
            return q, f"no {key} {ref!r} in this workspace"
        q = q.filter(Entries.id.in_(session.query(link.entry_id).filter(getattr(link, fk) == found[0])))
    for key, present in (("referenced_by", True), ("not_referenced_by", False)):
        if key in spec:
            pointing, note = _referencing(session, group_id, spec[key], key, session.get_bind().dialect.name)
            if note:
                return q, note
            q = q.filter(Entries.slug.in_(pointing) if present else Entries.slug.notin_(pointing))
    return q, None


def _referencing(session, group_id, by, key: str, dialect: str):
    """referenced_by / not_referenced_by: the slugs held in `field` by the entries of `entry_type` (out of the Trash, narrowed by `fields`),
    as a subquery, so a list of beats keeps those with lines in one query. Empty values never widen it (a note instead), and a pointing
    entry with nothing in its field is left out: NULL in a NOT IN would make it match nothing."""
    from sqlalchemy.orm import aliased

    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.automation.selector import json_field_equals

    if not isinstance(by, dict) or not str(by.get("entry_type") or "").strip() or not str(by.get("field") or "").strip():
        return None, f"{key} is {{entry_type, field, fields?}}: the entries whose field holds this one's slug"
    fields = by.get("fields") or {}
    if not isinstance(fields, dict):
        return None, f"{key}.fields is {{field_key: value}}"
    kind = str(by["entry_type"]).strip().lower()
    spellings = {kind, kind.replace("_", "-"), kind.replace("-", "_")}
    other = aliased(Entries)
    held = other.data_json[str(by["field"]).strip()].as_string()
    q = session.query(held).filter(
        other.group_id == group_id,
        other.status != "trashed",
        other.entry_type_id.in_(session.query(EntryTypes.id).filter(EntryTypes.group_id == group_id, EntryTypes.slug.in_(spellings))),
        held.isnot(None),
        held != "",
    )
    for field_key, value in fields.items():
        if value is None or value == "":
            return None, f"{key}.fields.{field_key} has no value"
        q = q.filter(json_field_equals(other.data_json, str(field_key), value, dialect))
    return q, None


def _uuids(refs: list[str]) -> list:
    import uuid

    out = []
    for ref in refs:
        try:
            out.append(uuid.UUID(ref))
        except ValueError:
            pass
    return out


def _positions(session, group_id, spec: dict) -> tuple[dict | None, str | None]:
    """entry id → place in the one collection the spec names (sort by position), or a note why there isn't one."""
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_collections import EntryCollections

    named = _as_list(spec.get("collection")) + _as_list(spec.get("collections"))
    if len(named) != 1:
        return None, "sort by position needs exactly one collection"
    named_match = (Collections.slug == named[0]) | (Collections.name == named[0])
    coll = session.query(Collections.id).filter(Collections.group_id == group_id, named_match).first()
    if coll is None:
        return None, f"no such collection(s) in this workspace: {named[0]}"
    rows = session.query(EntryCollections.entry_id, EntryCollections.sort_order).filter(EntryCollections.collection_id == coll[0])
    return dict(rows.all()), None


def _field_value(entry, key: str):
    if key.startswith("metadata."):
        return (entry.metadata_json or {}).get(key[len("metadata.") :])
    if key == "publish_status":
        return entry.status
    if key == "entry_type":
        return entry.entry_type.slug if entry.entry_type else None
    return (entry.data_json or {}).get(key.removeprefix("data."))


def _matches(actual, op: str, expected) -> bool:
    missing = actual is None or actual == "" or actual == []
    if op == "exists":
        return not missing
    if op == "missing":
        return missing
    if op in ("gt", "gte", "lt", "lte"):
        a, b = number_like(actual), number_like(expected)
        if a is None or b is None:
            return False
        return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
    if op == "contains":
        return not missing and str(expected).lower() in str(actual).lower()
    if op == "in":
        options = expected if isinstance(expected, list | tuple) else [expected]
        return any(_equal(actual, o) for o in options)
    if op == "neq":
        return not _equal(actual, expected)
    return _equal(actual, expected)  # eq


def condition_matches(entry, condition: dict) -> bool:
    """One ``where`` condition (``{"field", "op", "value"}``) against one entry.

    Shared with smart-collection rules, so a field condition means the same thing in a workflow
    query and in a collection's rules. The caller rejects unknown ops first; here one compares as eq.
    """
    return _matches(_field_value(entry, str(condition["field"])), str(condition.get("op") or "eq"), condition.get("value"))


def _equal(actual, expected) -> bool:
    from marvin.services.automation.matcher import _like

    return actual == _like(actual, expected)


_DIGITS = re.compile(r"(\d+)")
_LEADING_NUMBER = re.compile(r"^\s*[$€£]?\s*[-+]?\d")  # "45", "$1,170", "8 x 10"; not "tin-beat-1001", whose "-1001" is no number


def _sorts_as_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) or bool(_LEADING_NUMBER.match(str(value)))


def _sort_key(entry, by: str, numeric: bool):
    """A field's value to sort by: a number when every value is number-like, else text as people read it, numbers inside it as
    numbers ("beat-1001" before "beat-10001"; a beat's lines by their beat's slug, then their order)."""
    value = _field_value(entry, by)
    empty = value is None or value == ""
    if numeric:
        n = number_like(value)
        # alike numbers keep to the text, read naturally: a beat inserted after 04 is "04a", so 04 comes before 04a, not wherever it was found
        text = (
            tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in _DIGITS.split(str(value).lower()) if part)
            if value is not None
            else ()
        )
        return (n is None, n or 0.0, text)
    if empty:
        return (True, ())
    return (False, tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in _DIGITS.split(str(value).lower()) if part))


def _sort_by_field(entries: list, by: str, descending: bool) -> list:
    """Entries by one field (numbers as numbers, text naturally), those without a value last either way. Stable: entries alike keep
    the order they came in, so a second key is sorted first."""
    present = [v for v in (_field_value(e, by) for e in entries) if v is not None and v != ""]
    numeric = bool(present) and all(_sorts_as_number(v) for v in present)
    with_value = [e for e in entries if _field_value(e, by) not in (None, "")]
    without = [e for e in entries if _field_value(e, by) in (None, "")]
    with_value.sort(key=lambda e: _sort_key(e, by, numeric), reverse=descending)
    return with_value + without


def _sort_by_column(entries: list, by: str, descending: bool) -> list:
    """Entries by one of their own columns (title, created_at, ...), those without a value last. Stable, as ``_sort_by_field``."""
    attr = "update_at" if by == "updated_at" else by
    filled = [e for e in entries if getattr(e, attr) is not None]
    filled.sort(key=lambda e: getattr(e, attr) if attr != "title" else (e.title or "").lower(), reverse=descending)
    return filled + [e for e in entries if getattr(e, attr) is None]


def run(session, group_id, spec: dict | None, *, limit: int | None = None, offset: int = 0, exclude_types: tuple[str, ...] = ()) -> EntryQueryResult:
    """Resolve a spec to rows (after offset/limit) plus the true total, groups and any note."""
    from marvin.db.models.platform.entries import Entries

    spec = spec or {}
    q, note = build(session, group_id, spec, exclude_types=exclude_types)
    if note:
        return EntryQueryResult(rows=[], total=0, note=note)

    where = [w for w in (spec.get("where") or []) if isinstance(w, dict) and w.get("field")]
    unknown_ops = sorted({str(w.get("op")) for w in where if (w.get("op") or "eq") not in WHERE_OPS})
    if unknown_ops:
        # Fail closed: ignoring a condition would WIDEN the match — a workflow could act on entries
        # the author meant to exclude.
        note = f"unknown where op(s): {', '.join(unknown_ops)}. Valid: {', '.join(WHERE_OPS)}."
        return EntryQueryResult(rows=[], total=0, note=note, unknown_ops=unknown_ops)
    sort = spec.get("sort") if isinstance(spec.get("sort"), dict) else ({"by": spec["sort"]} if spec.get("sort") else None)
    sort_by = str((sort or {}).get("by") or "").strip()
    descending = str((sort or {}).get("direction") or "asc").lower() == "desc"
    group_by = str(spec.get("group_by") or "").strip()
    needs_scan = bool(where) or (sort_by and sort_by not in COLUMN_SORTS) or bool(group_by)

    if not needs_scan:
        if sort_by in COLUMN_SORTS:
            column = {
                "title": Entries.title,
                "created_at": Entries.created_at,
                "updated_at": Entries.update_at,
                "published_at": Entries.published_at,
            }[sort_by]
            q = q.order_by(column.desc() if descending else column.asc(), Entries.id)
        else:
            q = q.order_by(Entries.created_at.desc(), Entries.id)
        total = q.count()
        page = q.offset(max(0, offset))
        rows = page.limit(limit).all() if limit is not None else page.all()
        return EntryQueryResult(rows=rows, total=total, unknown_ops=unknown_ops)

    positions = None
    if sort_by == POSITION:
        positions, note = _positions(session, group_id, spec)
        if note:
            return EntryQueryResult(rows=[], total=0, note=note)
    candidates = q.order_by(Entries.created_at.desc(), Entries.id).limit(SCAN_CAP + 1).all()
    scan_capped = len(candidates) > SCAN_CAP
    candidates = candidates[:SCAN_CAP]
    matched = [e for e in candidates if all(condition_matches(e, w) for w in where)]

    groups = None
    if group_by:
        groups = {}
        for e in matched:
            value = _field_value(e, group_by)
            label = "(none)" if value is None or value == "" else str(value)
            groups[label] = groups.get(label, 0) + 1
        groups = dict(sorted(groups.items(), key=lambda kv: (-kv[1], kv[0])))

    if sort_by:
        if positions is not None:  # as the publishing API orders a collection: its order, then newest published
            oldest = datetime.min.replace(tzinfo=None)
            matched.sort(key=lambda e: (e.published_at or oldest).replace(tzinfo=None), reverse=True)
            matched.sort(key=lambda e: positions.get(e.id, 0), reverse=descending)
        elif sort_by in COLUMN_SORTS:
            matched = _sort_by_column(matched, sort_by, descending)
        else:
            then = str((sort or {}).get("then") or "").strip()
            if then in COLUMN_SORTS:  # alike in the first field, in the order they were made (a line's takes)
                matched = _sort_by_column(matched, then, descending)
            elif then and then != POSITION:  # a second field: alike in the first, by this (a beat's lines by order)
                matched = _sort_by_field(matched, then, descending)
            matched = _sort_by_field(matched, sort_by, descending)  # empty values last either way

    total = len(matched)
    start = max(0, offset)
    rows = matched[start : start + limit] if limit is not None else matched[start:]
    return EntryQueryResult(rows=rows, total=total, groups=groups, scan_capped=scan_capped, unknown_ops=unknown_ops)


# ── One entry per person ──────────────────────────────────────────────────────────────────────────
# A submittable type's `match_field` names the field that identifies the submitter. These two find the
# entry a repeat submission belongs to (routes/publish/forms_controller.py).


def identity_value(value) -> tuple[str, bool] | None:
    """A submitted value as the identity it names: ``(normalised, ignore_case)``, or None when it can't
    identify anyone (empty, a checkbox, a list). Whitespace is trimmed; an email address is also
    lower-cased and compared case-insensitively (``Ann@Example.com `` is ``ann@example.com``)."""
    from marvin.services.security.submission_protection import looks_like_email

    if value is None or isinstance(value, bool | dict | list):
        return None
    text = str(value).strip()
    if not text:
        return None
    if looks_like_email(text):
        return text.lower(), True
    return text, False


def find_by_identity(session, group_id, entry_type_id, field_key: str, value: str, *, ignore_case: bool = False):
    """The newest entry of ``entry_type_id`` whose ``field_key`` equals ``value`` (from
    :func:`identity_value`) after trimming the stored value — and lower-casing it when ``ignore_case``.
    Deleted entries are gone from the table and trashed ones are skipped, so neither matches (a repeat
    form submission from someone whose entry is in the Trash starts a new entry). None when there's no such entry."""
    import sqlalchemy as sa

    from marvin.db.models.platform.entries import Entries

    stored = sa.func.trim(Entries.data_json[field_key].as_string())
    if ignore_case:
        stored = sa.func.lower(stored)
    return (
        session.query(Entries)
        .filter(Entries.group_id == group_id, Entries.entry_type_id == entry_type_id, stored == value, Entries.status != "trashed")
        .order_by(Entries.created_at.desc())
        .first()
    )
