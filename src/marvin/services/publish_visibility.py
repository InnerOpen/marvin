"""What the publishing API serves — shared by the publishing controller and the site-rebuild trigger,
so "can a site see this?" has one answer."""


def is_publishable_type(entry_type) -> bool:
    """False only for an entry type whose capabilities say `publishable: false` — submissions (contact,
    newsletter signups…) and other private records. Absent capabilities count as publishable."""
    caps = entry_type.capabilities_json if isinstance(entry_type.capabilities_json, dict) else {}
    return caps.get("publishable") is not False


def non_publishable_type_ids(entry_types) -> list:
    """Ids of the entry types the publishing API never serves, whatever their entries' status."""
    return [et.id for et in entry_types if not is_publishable_type(et)]


def _site_metadata_images(prefs) -> list[str]:
    """The strings in the site's ``metadata.brand`` (a brand value names an asset only sometimes — the
    caller matches them against one asset) and its structured SEO share image."""
    metadata = getattr(prefs, "site_metadata_json", None)
    if not isinstance(metadata, dict):
        return []
    brand = metadata.get("brand")
    seo = metadata.get("seo")
    values = list(brand.values()) if isinstance(brand, dict) else []
    values.append(seo.get("image") if isinstance(seo, dict) else None)
    return [v.strip() for v in values if isinstance(v, str) and v.strip()]


def _in_published_entry_data(session, kind: str, row) -> bool:
    """Whether a published entry of a publishable type holds this item's id in one of its asset / resource
    fields. ``data_json`` is plain JSON (no containment operator), so the entries whose data text mentions
    the id are fetched and only those are checked against the type's field types."""
    from sqlalchemy import Text, cast
    from sqlalchemy.orm import joinedload

    from marvin.db.models.platform import Entries
    from marvin.services.publish_entry_links import linked_ids

    candidates = (
        session.query(Entries)
        .options(joinedload(Entries.entry_type))
        .filter(Entries.group_id == row.group_id, Entries.status == "published", cast(Entries.data_json, Text).ilike(f"%{row.id}%"))
        .all()
    )
    return any(e.entry_type is not None and is_publishable_type(e.entry_type) and row.id in linked_ids(e, kind) for e in candidates)


def item_visible_to_sites(session, kind: str, row) -> bool:
    """Whether a site can see this asset or resource (``kind`` "asset"/"resource"), trashed or not: it is
    attached to a published entry of a publishable type, one of that entry's asset / resource fields holds
    its id (``publish_entry_links``), it is in a collection visible to sites, or — an asset — the site
    settings name it as the logo, favicon, share image or a ``metadata.brand`` value. The site-rebuild
    trigger asks this when one goes into or comes out of the Trash."""
    from marvin.db.models.platform import CollectionAssets, CollectionResources, Collections, Entries, EntryAssets, EntryResources, EntryTypes

    link, member = (EntryAssets, CollectionAssets) if kind == "asset" else (EntryResources, CollectionResources)
    key = "asset_id" if kind == "asset" else "resource_id"
    entries = (
        session.query(EntryTypes)
        .join(Entries, Entries.entry_type_id == EntryTypes.id)
        .join(link, link.entry_id == Entries.id)
        .filter(getattr(link, key) == row.id, Entries.status == "published")
        .all()
    )
    if any(is_publishable_type(et) for et in entries):
        return True
    if _in_published_entry_data(session, kind, row):
        return True
    public = (
        session.query(member.id)
        .join(Collections, Collections.id == member.collection_id)
        .filter(getattr(member, key) == row.id, Collections.is_public.is_(True))
        .first()
    )
    if public is not None:
        return True
    if kind == "asset":
        from marvin.db.models.groups.preferences import GroupPreferencesModel

        prefs = session.query(GroupPreferencesModel).filter_by(group_id=row.group_id).first()
        named = [n for n in (getattr(prefs, "site_logo", None), getattr(prefs, "site_favicon", None), *_site_metadata_images(prefs)) if n]
        # By slug or id (what the publishing API's site settings carry), or by its URL / storage key.
        return any(n in (row.slug, str(row.id)) or (row.storage_key and row.storage_key in n) for n in named)
    return False


def item_served_to_sites(session, kind: str, row) -> bool:
    """Whether the publishing API serves this asset or resource right now: not in the Trash, and a site can
    see it (``item_visible_to_sites``). What an edit to it, or its deletion, changes for a site — a trashed
    item is already gone from the API, so deleting it for good changes nothing."""
    return getattr(row, "trashed_at", None) is None and item_visible_to_sites(session, kind, row)


def tag_served_to_sites(session, tag_id) -> bool:
    """Whether a tag is on something the publishing API serves — a published entry of a publishable type, or an asset
    or resource a site can see. Renaming or deleting such a tag changes what a site gets; one on nothing served doesn't."""
    from marvin.db.models.platform import Assets, AssetTags, Entries, EntryTags, EntryTypes, Resources, ResourceTags

    published = (
        session.query(Entries.entry_type_id)
        .join(EntryTags, EntryTags.entry_id == Entries.id)
        .filter(EntryTags.tag_id == tag_id, Entries.status == "published")
        .distinct()
        .all()
    )
    type_ids = {row[0] for row in published}
    if None in type_ids:
        return True  # an untyped entry: can't say it isn't served
    if type_ids and any(is_publishable_type(et) for et in session.query(EntryTypes).filter(EntryTypes.id.in_(type_ids)).all()):
        return True
    for kind, model, junction, key in (("asset", Assets, AssetTags, "asset_id"), ("resource", Resources, ResourceTags, "resource_id")):
        rows = session.query(model).join(junction, getattr(junction, key) == model.id).filter(junction.tag_id == tag_id).all()
        if any(item_served_to_sites(session, kind, row) for row in rows):
            return True
    return False
