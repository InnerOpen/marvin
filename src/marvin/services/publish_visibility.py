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


def item_visible_to_sites(session, kind: str, row) -> bool:
    """Whether a site can see this asset or resource (``kind`` "asset"/"resource"), trashed or not: it is
    attached to a published entry of a publishable type, it is in a collection visible to sites, or — an
    asset — the site settings name it as the logo or favicon. The site-rebuild trigger asks this when one
    goes into or comes out of the Trash."""
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
        named = [n for n in (getattr(prefs, "site_logo", None), getattr(prefs, "site_favicon", None)) if n]
        # By slug or id (what the publishing API's site settings carry), or by its URL / storage key.
        return any(n in (row.slug, str(row.id)) or (row.storage_key and row.storage_key in n) for n in named)
    return False
