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
  Trash still counts as attached, so restoring that entry never finds its image gone. An original one of whose
  versions an entry uses counts as attached. A version made from an
  original still in the library is never "unattached": it goes with its original, so a cleanup of unattached
  images can't sweep a crop pack — unless the spec asks for versions itself (``versions: true`` or ``source``).
- ``entry`` — attached to this entry (id or slug), in the entry's own order; ``role`` — assets only: attached in this
  role (``hero``), to that entry or, without ``entry``, to any.
- ``exclude`` — leave this item out (id or slug): "the others", e.g. ``${asset.id}`` in a run about that asset.
- ``checksum`` — assets only: exactly this file (its sha256), e.g. ``${asset.checksum}`` to find a re-upload.
- ``created_after`` / ``created_before`` — ISO dates or datetimes (UTC), or relative (``-7d``).
- ``trashed`` — true: only items in the Trash (the Trash's side, for a restore).
- ``origin`` / ``origins`` — assets only: upload, derived (made from another asset) or generated (by an integration).
- ``versions`` — assets only: false leaves out versions of an original that is still in the library (the library's
  folded view); true keeps only versions; all keeps both. Unset means both here, but a workflow's asset target
  defaults to false (services/automation/selector.py). ``source`` — the versions made from this asset (id or slug).

Items in the Trash are left out unless ``trashed`` asks for them (the key, or the ``trashed=True`` argument). A
filter naming a tag or collection that doesn't exist matches nothing and says so in the note — dropping it
would widen the selection.
"""

import uuid
from dataclasses import dataclass

from marvin.services.automation.matcher import as_bool
from marvin.services.entries.query import _as_list, _when

ASSET, RESOURCE = "asset", "resource"
_COMMON = ("text", "query", "tags", "collection", "collections", "unattached", "entry", "exclude", "created_after", "created_before", "trashed")
KEYS = {
    ASSET: (*_COMMON, "asset_type", "asset_types", "mime_type", "mime_types", "origin", "origins", "versions", "source", "role", "checksum"),
    RESOURCE: (*_COMMON, "resource_type", "resource_types"),
}

ASSET_TYPES = ("image", "svg", "document", "video", "audio", "archive", "other")
ORIGINS = ("upload", "derived", "generated")

# What each key means, in a line — the agent's workflow authoring guide lists these for an asset or resource
# target's `query` (test_workflow_item_targets keeps them matching KEYS).
KEY_NOTES: dict[str, dict[str, str]] = {
    kind: {
        "text": "name or slug contains (an asset also by filename; same as `query`)",
        "query": "same as `text`",
        "tags": "has any of these tags (slug or name)",
        "collection": "in this collection (slug or name; `collections`: a list)",
        "collections": "in any of these collections",
        "unattached": "true: attached to no entry (an asset's versions of an original still in the library don't count); "
        "false: attached to at least one",
        "entry": "attached to this entry (id or slug), in its order",
        "exclude": "leave this one out (id or slug), e.g. ${asset.id}",
        "created_after": "ISO date/datetime (UTC) or relative: -7d, -12h, -2w, now, today; also created_before",
        "created_before": "a date, as created_after",
        "trashed": "true: only items in the Trash (left out otherwise) — a `restore` target",
        **(
            {
                "asset_type": f"one of {', '.join(ASSET_TYPES)} (`asset_types`: a list)",
                "asset_types": "asset types, any of",
                "mime_type": "exact MIME type, e.g. image/svg+xml (`mime_types`: a list)",
                "mime_types": "MIME types, any of",
                "origin": f"one of {', '.join(ORIGINS)} (`origins`: a list) — derived: made from another asset",
                "origins": "origins, any of",
                "versions": "false: leave out versions of an original still in the library; true: only versions; all: both "
                "(a workflow's asset target leaves them out unless it sets versions, source or origin derived)",
                "source": "the versions made from this asset (id or slug)",
                "role": "attached in this role (e.g. hero), to `entry` or to any entry",
                "checksum": "exactly this file (sha256), e.g. ${asset.checksum}",
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
        q, note = _asset_lineage(session, group_id, q, spec)
        if note:
            return nothing, note
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

    q, note = _exclude_and_checksum(q, model, kind, spec)
    if note:
        return nothing, note

    if "entry" in spec or (kind == ASSET and "role" in spec):
        q, note = _attached_to(session, group_id, q, model, entry_link, fk, spec)
        if note:
            return nothing, note

    if spec.get("unattached") is not None:
        unattached = as_bool(str(spec["unattached"]))
        if unattached is None:
            return nothing, f"unattached is true or false, not {spec['unattached']!r}"
        linked = model.id.in_(session.query(getattr(entry_link, fk)))
        if kind == ASSET:  # an original whose version an entry uses (a hero's web sizes) is in use too
            # (NOT IN over a column with NULLs matches nothing, so the originals' NULL sources are left out.)
            used_sources = sa.select(Assets.source_asset_id).where(Assets.source_asset_id.isnot(None), Assets.id.in_(sa.select(EntryAssets.asset_id)))
            linked = linked | model.id.in_(used_sources)
        q = q.filter(~linked if unattached else linked)
        if unattached and kind == ASSET and not (as_bool(str(spec.get("versions"))) is True or spec.get("source")):
            q = q.filter(sa.or_(Assets.source_asset_id.is_(None), Assets.source_asset_id.not_in(live_originals(group_id))))

    for key, keep in (("created_after", lambda at: model.created_at >= at), ("created_before", lambda at: model.created_at < at)):
        if spec.get(key):
            if (at := _when(spec[key])) is None:
                return nothing, f"{key} is not a date: {spec[key]!r} (an ISO date, or relative like -7d, -12h, -2w, now, today)"
            q = q.filter(keep(at))
    return q, None


def _exclude_and_checksum(q, model, kind: str, spec: dict):
    """exclude (one item left out) / checksum (assets: exactly this file). Present but empty matches nothing."""
    from marvin.services.entries.query import _uuids

    if "exclude" in spec:
        ref = str(spec["exclude"] or "").strip()
        if not ref:
            return q, "exclude has no value"
        q = q.filter(~((model.slug == ref) | model.id.in_(_uuids([ref]))))
    if kind == ASSET and "checksum" in spec:
        checksum = str(spec["checksum"] or "").strip()
        if not checksum:
            return q, "checksum has no value"
        q = q.filter(model.checksum == checksum)
    return q, None


def _attached_to(session, group_id, q, model, link, fk: str, spec: dict):
    """entry / role: the links an entry has. A key present with nothing in it, or an entry that isn't there, matches
    nothing — a template that resolved to nothing must never widen the selection."""
    from marvin.db.models.platform.entries import Entries
    from marvin.services.entries.query import _uuids

    links = session.query(getattr(link, fk))
    if "entry" in spec:
        ref = str(spec["entry"] or "").strip()
        if not ref:
            return q, "entry has no value"
        found = session.query(Entries.id).filter(Entries.group_id == group_id, (Entries.slug == ref) | Entries.id.in_(_uuids([ref]))).first()
        if found is None:
            return q, f"no entry {ref!r} in this workspace"
        links = links.filter(link.entry_id == found[0])
    if "role" in spec:
        if not str(spec["role"] or "").strip():
            return q, "role has no value"
        links = links.filter(link.role == str(spec["role"]).strip())
    return q.filter(model.id.in_(links)), None


def _entry_order(session, group_id, kind: str, spec: dict):
    """{item id: position} on the entry ``spec`` names, so its pictures come in the entry's own order."""
    from marvin.db.models.platform import EntryAssets, EntryResources
    from marvin.db.models.platform.entries import Entries
    from marvin.services.entries.query import _uuids

    link, fk = (EntryAssets, "asset_id") if kind == ASSET else (EntryResources, "resource_id")
    ref = str(spec.get("entry") or "").strip()
    entry = session.query(Entries.id).filter(Entries.group_id == group_id, (Entries.slug == ref) | Entries.id.in_(_uuids([ref]))).first()
    if entry is None:
        return {}
    return dict(session.query(getattr(link, fk), link.position).filter(link.entry_id == entry[0]).all())


def live_originals(group_id):
    """The ids of the workspace's library assets not in the Trash — an asset whose source is one of them is a
    version of a live original (folded under it in the library, kept out of unattached-image cleanups)."""
    import sqlalchemy as sa

    from marvin.db.models.platform import Assets

    return sa.select(Assets.id).where(Assets.group_id == group_id, Assets.trashed_at.is_(None), Assets.scope == "library")


def _asset_lineage(session, group_id, q, spec: dict):
    """origin / versions / source: what an asset was made from (Assets.origin, Assets.source_asset_id)."""
    import sqlalchemy as sa

    from marvin.db.models.platform import Assets

    if origins := _as_list(spec.get("origin")) + _as_list(spec.get("origins")):
        if bad := [o for o in origins if o not in ORIGINS]:
            return q, f"origin is one of {', '.join(ORIGINS)}, not {', '.join(map(str, bad))}"
        q = q.filter(Assets.origin.in_(origins))
    if spec.get("versions") is not None and str(spec["versions"]).lower() != "all":  # "all": originals and versions
        versions = as_bool(str(spec["versions"]))
        if versions is None:
            return q, f"versions is true, false or all, not {spec['versions']!r}"
        if versions:
            q = q.filter(Assets.source_asset_id.isnot(None))
        else:  # a version whose original is gone or in the Trash stands on its own
            q = q.filter(sa.or_(Assets.source_asset_id.is_(None), Assets.source_asset_id.not_in(live_originals(group_id))))
    if ref := spec.get("source"):
        ref = str(ref).strip()
        match = Assets.slug == ref
        try:
            match = match | (Assets.id == uuid.UUID(ref))
        except ValueError:
            pass
        found = session.query(Assets.id).filter(Assets.group_id == group_id, match).first()
        if found is None:
            return q, f"no asset {ref!r} in this workspace"
        q = q.filter(Assets.source_asset_id == found[0])
    return q, None


def run(session, group_id, kind: str, spec: dict | None, *, trashed: bool = False, limit: int | None = None) -> ItemQueryResult:
    """Resolve a spec to rows (by name, at most ``limit``) plus the true total and any note."""
    q, note = build(session, group_id, kind, spec, trashed=trashed)
    if note:
        return ItemQueryResult(rows=[], total=0, note=note)
    model = q.column_descriptions[0]["entity"]
    total = q.count()
    page = q.order_by(model.name, model.id)
    if (spec or {}).get("entry"):  # the entry's own order (a gallery as it shows), by name after that
        order = _entry_order(session, group_id, kind, spec)
        rows = sorted(page.all(), key=lambda r: order.get(r.id, len(order)))
        return ItemQueryResult(rows=rows[:limit] if limit is not None else rows, total=total)
    return ItemQueryResult(rows=page.limit(limit).all() if limit is not None else page.all(), total=total)
