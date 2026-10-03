"""One entry query for every surface that finds entries matching a description.

The agent's `find_entries`, a workflow's "Run on a query of entries" (and an entry step's
`entity_query`) and the agent's bulk actions all used to build their own query, each knowing a
different subset of filters. They now share this one, so a filter added here works everywhere.

A spec is a plain dict (all keys optional, unknown keys ignored):

- ``entry_type`` / ``entry_types`` — type slug(s); `bench_note` and `bench-note` both match.
- ``status`` / ``statuses`` — the PUBLISH status (inbox, draft, needs_review, approved, published,
  archived). A value that isn't one (usually a field's value) yields a note instead of a silent 0.
- ``text`` / ``query`` — title or slug contains (case-insensitive).
- ``tags`` — any of these tags (slug or name). ``collection`` / ``collections`` — in any of these (slug or name).
- ``has_images`` / ``has_assets`` / ``has_resources``.
- ``fields`` / ``data`` — exact match on the entry type's own fields ``{key: value}``; ``metadata`` the same on
  metadata. Typed-in text matches checkbox/number values. An empty value matches nothing.
- ``where`` — ``[{"field": key, "op": op, "value": v}]``; ``field`` is a field key, or ``metadata.<key>``.
  ``op``: eq, neq, in, contains, exists, missing, gt, gte, lt, lte. Comparisons read number-like text
  (`"$1,170"` → 1170), so they work on fields stored as text.
- ``created_after``/``created_before``, ``updated_after``/``updated_before``, ``published_after``/``published_before``
  — ISO dates or datetimes (UTC).
- ``sort`` — ``{"by": "title"|"created_at"|"updated_at"|"published_at"|<field key>, "direction": "asc"|"desc"}``;
  a field sorts numerically when its values are number-like, else as text; empty values sort last.
- ``group_by`` — a field key, or ``publish_status`` / ``entry_type``: counts per value over the whole match.

In ``where``, ``sort`` and ``group_by`` a bare key is always the entry type's own field (a type may well
have its own ``status`` field); ``publish_status`` and ``entry_type`` name the entry's built-ins.

Everything that SQL can express portably runs in SQL. ``where``, sorting by a field and ``group_by``
need per-row reading (number-like text, JSON values), so they run over the SQL-filtered rows in Python,
bounded by ``SCAN_CAP`` — and the result says when that bound was hit.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCAN_CAP = 5000
"""Most rows read into memory for where / sort-by-field / group_by; a workspace bigger than this gets `scan_capped`."""

WHERE_OPS = ("eq", "neq", "in", "contains", "exists", "missing", "gt", "gte", "lt", "lte")
COLUMN_SORTS = ("title", "created_at", "updated_at", "published_at")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class EntryQueryResult:
    rows: list
    total: int
    note: str | None = None
    groups: dict[str, int] | None = None
    scan_capped: bool = False
    unknown_ops: list[str] = field(default_factory=list)


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


def _when(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build(session, group_id, spec: dict | None):
    """The SQL part of a spec: (query over Entries, note). The note explains a filter that can't match."""
    import sqlalchemy as sa

    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.db.models.platform.entry_resources import EntryResources
    from marvin.db.models.platform.entry_tags import EntryTags
    from marvin.db.models.platform.entry_types import EntryTypes
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

    collections = _as_list(spec.get("collection")) + _as_list(spec.get("collections"))
    if collections:
        coll_ids = session.query(Collections.id).filter(
            Collections.group_id == group_id, Collections.slug.in_(collections) | Collections.name.in_(collections)
        )
        q = q.filter(Entries.id.in_(session.query(EntryCollections.entry_id).filter(EntryCollections.collection_id.in_(coll_ids))))

    if spec.get("has_images"):
        image_links = session.query(EntryAssets.entry_id).join(Assets, Assets.id == EntryAssets.asset_id).filter(Assets.asset_type == "image")
        q = q.filter(Entries.id.in_(image_links))
    elif spec.get("has_assets"):
        q = q.filter(Entries.id.in_(session.query(EntryAssets.entry_id)))
    if spec.get("has_resources"):
        q = q.filter(Entries.id.in_(session.query(EntryResources.entry_id)))

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
        if after:
            q = q.filter(column >= after)
        if before:
            q = q.filter(column < before)

    return q, None


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


def _sort_key(entry, by: str, numeric: bool):
    value = _field_value(entry, by)
    empty = value is None or value == ""
    if numeric:
        n = number_like(value)
        return (n is None, n or 0.0)
    return (empty, str(value).lower() if not empty else "")


def run(session, group_id, spec: dict | None, *, limit: int | None = None, offset: int = 0) -> EntryQueryResult:
    """Resolve a spec to rows (after offset/limit) plus the true total, groups and any note."""
    from marvin.db.models.platform.entries import Entries

    spec = spec or {}
    q, note = build(session, group_id, spec)
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
        if sort_by in COLUMN_SORTS:
            attr = "update_at" if sort_by == "updated_at" else sort_by
            filled = [e for e in matched if getattr(e, attr) is not None]
            filled.sort(key=lambda e: getattr(e, attr) if attr != "title" else (e.title or "").lower(), reverse=descending)
            matched = filled + [e for e in matched if getattr(e, attr) is None]
        else:
            values = [_field_value(e, sort_by) for e in matched]
            present = [v for v in values if v is not None and v != ""]
            numeric = bool(present) and all(number_like(v) is not None for v in present)
            with_value = [e for e in matched if _field_value(e, sort_by) not in (None, "")]
            without = [e for e in matched if _field_value(e, sort_by) in (None, "")]
            with_value.sort(key=lambda e: _sort_key(e, sort_by, numeric), reverse=descending)
            matched = with_value + without  # empty values last either way

    total = len(matched)
    start = max(0, offset)
    rows = matched[start : start + limit] if limit is not None else matched[start:]
    return EntryQueryResult(rows=rows, total=total, groups=groups, scan_capped=scan_capped, unknown_ops=unknown_ops)
