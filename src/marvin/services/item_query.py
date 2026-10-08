"""One query for assets and resources — the counterpart of services/entries/query.py.

The agent's `list_assets` / `list_resources`, `attach_tag`'s `filter` and `trash_entries` / `restore_entries`'
`match` all select assets and resources by the same description, so they share this query: a filter added
here works everywhere.

A spec is a plain dict (all keys optional, unknown keys ignored — callers that must not widen a selection
check ``unknown_keys`` first):

- ``asset_type`` / ``asset_types`` — the coarse bucket (image, svg, document, …) — assets only.
- ``mime_type`` / ``mime_types`` — exact MIME, e.g. ``image/svg+xml`` — assets only, finer than asset_types.
- ``resource_type`` / ``resource_types`` — resources only.
- ``text`` / ``query`` — name or slug (an asset also by filename) contains, case-insensitive.
- ``tags`` — carrying ANY of these tags (slug or name).
- ``collection`` / ``collections`` — in any of these collections (slug or name).
- ``unattached`` — true: attached to no entry; false: attached to at least one. A link to an entry in the
  Trash still counts as attached, so restoring that entry never finds its image gone.
- ``created_after`` / ``created_before`` — ISO dates or datetimes (UTC).
- ``trashed`` — true: only items in the Trash (the Trash's side, for a restore).

Items in the Trash are left out unless ``trashed`` asks for them (the key, or the ``trashed=True`` argument). A
filter naming a tag or collection that doesn't exist matches nothing and says so in the note — dropping it
would widen the selection.
"""

from dataclasses import dataclass

from marvin.services.automation.matcher import as_bool
from marvin.services.entries.query import _as_list, _when

ASSET, RESOURCE = "asset", "resource"
_COMMON = ("text", "query", "tags", "collection", "collections", "unattached", "created_after", "created_before", "trashed")
KEYS = {
    ASSET: (*_COMMON, "asset_type", "asset_types", "mime_type", "mime_types"),
    RESOURCE: (*_COMMON, "resource_type", "resource_types"),
}

ASSET_TYPES = ("image", "svg", "document", "video", "audio", "archive", "other")

# What each key means, in a line — the agent's workflow authoring guide lists these for an asset or resource
# target's `query` (test_workflow_item_targets keeps them matching KEYS).
KEY_NOTES: dict[str, dict[str, str]] = {
    kind: {
        "text": "name or slug contains (an asset also by filename; same as `query`)",
        "query": "same as `text`",
        "tags": "has any of these tags (slug or name)",
        "collection": "in this collection (slug or name; `collections`: a list)",
        "collections": "in any of these collections",
        "unattached": "true: attached to no entry; false: attached to at least one",
        "created_after": "ISO date/datetime (UTC); also created_before",
        "created_before": "ISO date/datetime (UTC)",
        "trashed": "true: only items in the Trash (left out otherwise) — a `restore` target",
        **(
            {
                "asset_type": f"one of {', '.join(ASSET_TYPES)} (`asset_types`: a list)",
                "asset_types": "asset types, any of",
                "mime_type": "exact MIME type, e.g. image/svg+xml (`mime_types`: a list)",
                "mime_types": "MIME types, any of",
            }
            if kind == ASSET
            else {"resource_type": "the resource's type, e.g. supplier (`resource_types`: a list)", "resource_types": "resource types, any of"}
        ),
    }
    for kind in (ASSET, RESOURCE)
}


@dataclass
class ItemQueryResult:
    rows: list
    total: int
    note: str | None = None


def unknown_keys(kind: str, spec: dict | None) -> list[str]:
    """The spec's keys this query does not understand for ``kind`` (e.g. ``asset_types`` on resources)."""
    return sorted(k for k in (spec or {}) if k not in KEYS[kind])


def build(session, group_id, kind: str, spec: dict | None, *, trashed: bool = False):
    """(query over the kind's model, note). The note explains a filter that can't match."""
    import sqlalchemy as sa

    from marvin.db.models.platform import (
        Assets,
        AssetTags,
        CollectionAssets,
        CollectionResources,
        Collections,
        EntryAssets,
        EntryResources,
        Resources,
        ResourceTags,
        Tags,
    )

    spec = spec or {}
    model, tag_link, coll_link, entry_link, fk = {
        ASSET: (Assets, AssetTags, CollectionAssets, EntryAssets, "asset_id"),
        RESOURCE: (Resources, ResourceTags, CollectionResources, EntryResources, "resource_id"),
    }[kind]
    trashed = trashed or as_bool(str(spec.get("trashed"))) is True
    q = session.query(model).filter(model.group_id == group_id)
    q = q.filter(model.trashed_at.isnot(None) if trashed else model.trashed_at.is_(None))
    if kind == ASSET:  # the library: Ask files (chat attachments, services/assets/scope.py) aren't in it
        q = q.filter(Assets.scope == "library")
    nothing = q.filter(sa.false())

    if kind == ASSET:
        if types := _as_list(spec.get("asset_type")) + _as_list(spec.get("asset_types")):
            q = q.filter(Assets.asset_type.in_(types))
        if mimes := _as_list(spec.get("mime_type")) + _as_list(spec.get("mime_types")):
            q = q.filter(Assets.mime_type.in_(mimes))
    elif types := _as_list(spec.get("resource_type")) + _as_list(spec.get("resource_types")):
        q = q.filter(Resources.resource_type.in_(types))

    if text := spec.get("text") or spec.get("query"):
        like = f"%{text}%"
        match = model.name.ilike(like) | model.slug.ilike(like)
        if kind == ASSET:
            match = match | Assets.original_filename.ilike(like)
        q = q.filter(match)

    if tags := _as_list(spec.get("tags")):
        tag_ids = [r[0] for r in session.query(Tags.id).filter(Tags.group_id == group_id, Tags.slug.in_(tags) | Tags.name.in_(tags))]
        if not tag_ids:
            return nothing, f"no such tag(s) in this workspace: {', '.join(tags)}"
        q = q.filter(model.id.in_(session.query(getattr(tag_link, fk)).filter(tag_link.tag_id.in_(tag_ids))))

    if collections := _as_list(spec.get("collection")) + _as_list(spec.get("collections")):
        coll_ids = [
            r[0]
            for r in session.query(Collections.id).filter(
                Collections.group_id == group_id, Collections.slug.in_(collections) | Collections.name.in_(collections)
            )
        ]
        if not coll_ids:
            return nothing, f"no such collection(s) in this workspace: {', '.join(collections)}"
        q = q.filter(model.id.in_(session.query(getattr(coll_link, fk)).filter(coll_link.collection_id.in_(coll_ids))))

    if spec.get("unattached") is not None:
        unattached = as_bool(str(spec["unattached"]))
        if unattached is None:
            return nothing, f"unattached is true or false, not {spec['unattached']!r}"
        linked = model.id.in_(session.query(getattr(entry_link, fk)))
        q = q.filter(~linked if unattached else linked)

    for key, keep in (("created_after", lambda at: model.created_at >= at), ("created_before", lambda at: model.created_at < at)):
        if spec.get(key):
            if (at := _when(spec[key])) is None:
                return nothing, f"{key} is not a date: {spec[key]!r}"
            q = q.filter(keep(at))
    return q, None


def run(session, group_id, kind: str, spec: dict | None, *, trashed: bool = False, limit: int | None = None) -> ItemQueryResult:
    """Resolve a spec to rows (by name, at most ``limit``) plus the true total and any note."""
    q, note = build(session, group_id, kind, spec, trashed=trashed)
    if note:
        return ItemQueryResult(rows=[], total=0, note=note)
    model = q.column_descriptions[0]["entity"]
    total = q.count()
    page = q.order_by(model.name, model.id)
    return ItemQueryResult(rows=page.limit(limit).all() if limit is not None else page.all(), total=total)
