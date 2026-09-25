"""Smart collections: rule-based, materialized membership.

A collection with ``is_smart=True`` carries ``smart_rules`` describing which entries belong to
it (by entry-type slug and/or status). Membership is **materialized** into ``EntryCollections``
rows — kept in sync by an event-bus reaction on entry lifecycle changes and re-evaluated when a
collection's rules change — so the read path (renderers-core, publishing) is unchanged: it reads
junction rows exactly as for a manually-curated collection.

Rule shape (every dimension optional; an absent/empty dimension is not constrained)::

    {
      "entry_types": ["<slug>", "<slug>"],         # entry_type slugs
      "statuses": ["published"],                   # entry.status values
      "tags": ["<tag>", "<tag>"],                  # RESERVED — matches once entries carry tags
      "published_within_days": 30,                 # entries published in the last N days
      "created_within_days": 30,                   # any item created in the last N days
      "match": "all" | "any"                       # combine dimensions (default "all")
    }

The ``*_within_days`` dimensions are *rolling*: an item silently ages out of the window. Membership
is materialized, so nothing re-evaluates it on its own — the nightly ``resync_smart_collections``
task is what evicts items that have aged out. A collection using them is therefore accurate to
within one reconcile pass, which is the right trade for "recent": exact-to-the-second membership
would mean re-evaluating every smart collection on every read.

An empty rule set matches **nothing** — so a misconfigured smart collection can't silently
swallow the whole workspace.

``tags`` is wired as a forward-compatible dimension: it reads ``entry.tags`` when present and
is simply inert until a tagging system lands. The plan is one shared tag vocabulary across
entries, assets, and resources, so the same rule dimension will generalize to smart collections
of any of those once tags exist.

MVP scope: a smart collection's membership is *fully* rule-derived (smart XOR manual) — these
helpers add/remove only to reflect the rules; manual pins on a smart collection are not
preserved. Mixed smart+manual collections are a later enhancement.

The sync helpers never commit — the caller owns the transaction.
"""

from datetime import UTC, datetime, timedelta

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)


TARGET_TYPES = ("entry", "asset", "resource")


def _within_days(value, days) -> bool:
    """True when ``value`` is a datetime no older than ``days`` days.

    Fails closed: a missing date, an unparseable window, or a non-positive one matches nothing
    rather than dropping the constraint — a misconfigured window must never widen a collection to
    the whole workspace. Date columns are naive UTC (``NaiveDateTime``), so naive values are read
    as UTC rather than local time.
    """
    if value is None:
        return False
    try:
        days = float(days)
    except (TypeError, ValueError):
        return False
    if days <= 0:
        return False
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=UTC)
    return value >= datetime.now(UTC) - timedelta(days=days)


def matches_rules(item, rules: dict | None, target_type: str = "entry") -> bool:
    """Return True if ``item`` satisfies a smart collection's ``rules`` for ``target_type``.

    Dimensions are type-specific except ``tags`` (universal, matched on slugs):
      entry    → entry_types (entry_type.slug), statuses (status), published_within_days (published_at)
      asset    → asset_types (asset_type), mime_types (mime_type, exact e.g. image/svg+xml)
      resource → resource_types (resource_type)
    ``tags`` and ``created_within_days`` are universal. An empty/None rule set — or one with no recognized dimension — matches nothing.
    """
    if not rules:
        return False

    dimensions: list[bool] = []

    if target_type == "entry":
        entry_types = rules.get("entry_types")
        if entry_types:
            dimensions.append(getattr(getattr(item, "entry_type", None), "slug", None) in entry_types)
        statuses = rules.get("statuses")
        if statuses:
            dimensions.append(getattr(item, "status", None) in statuses)
        published_within = rules.get("published_within_days")
        if published_within is not None:
            dimensions.append(_within_days(getattr(item, "published_at", None), published_within))
    elif target_type == "asset":
        asset_types = rules.get("asset_types")
        if asset_types:
            dimensions.append(getattr(item, "asset_type", None) in asset_types)
        mime_types = rules.get("mime_types")
        if mime_types:  # exact MIME (e.g. "image/svg+xml") — finer than the asset_type bucket
            dimensions.append(getattr(item, "mime_type", None) in mime_types)
    elif target_type == "resource":
        resource_types = rules.get("resource_types")
        if resource_types:
            dimensions.append(getattr(item, "resource_type", None) in resource_types)

    created_within = rules.get("created_within_days")
    if created_within is not None:
        dimensions.append(_within_days(getattr(item, "created_at", None), created_within))

    tags = rules.get("tags")
    if tags:
        # Compare on slugs so a rule matches whether it stored "Chore Coat" or "chore-coat".
        from slugify import slugify

        want = {slugify(str(t)) for t in tags}
        have = set(getattr(item, "tag_names", None) or [])
        dimensions.append(bool(want & have))

    if not dimensions:
        return False

    if rules.get("match") == "any":
        return any(dimensions)
    return all(dimensions)


def entry_matches_rules(entry, rules: dict | None) -> bool:
    """Back-compat shim — entry-target matching. Prefer ``matches_rules(item, rules, target_type)``."""
    return matches_rules(entry, rules, "entry")


def _membership(target_type: str):
    """(model, junction, fk_field) for a target type's membership junction."""
    from marvin.db.models.platform import (
        Assets,
        CollectionAssets,
        CollectionResources,
        Entries,
        EntryCollections,
        Resources,
    )

    return {
        "entry": (Entries, EntryCollections, "entry_id"),
        "asset": (Assets, CollectionAssets, "asset_id"),
        "resource": (Resources, CollectionResources, "resource_id"),
    }[target_type]


def _smart_collections(session, group_id):
    from marvin.db.models.platform.collections import Collections

    return session.query(Collections).filter_by(group_id=group_id, is_smart=True).all()


def sync_item(session, group_id, item, target_type: str = "entry") -> int:
    """Sync one item's membership across every smart collection of its ``target_type``.

    Adds the item to smart collections whose rules it now matches and removes it from those it no
    longer matches. Returns the number of membership rows changed. Does not commit.
    """
    _model, junction, fk = _membership(target_type)
    changed = 0
    for collection in _smart_collections(session, group_id):
        if getattr(collection, "target_type", "entry") != target_type:
            continue
        desired = matches_rules(item, collection.smart_rules, target_type)
        existing = session.query(junction).filter(getattr(junction, fk) == item.id, junction.collection_id == collection.id).first()
        if desired and existing is None:
            session.add(junction(**{fk: item.id, "collection_id": collection.id, "sort_order": 0}))
            changed += 1
        elif not desired and existing is not None:
            session.delete(existing)
            changed += 1
    return changed


def sync_entry(session, group_id, entry) -> int:
    """Sync one entry's smart-collection membership. Thin wrapper over ``sync_item``."""
    return sync_item(session, group_id, entry, "entry")


def sync_collection(session, group_id, collection) -> int:
    """Re-evaluate one smart collection's membership across all items of its target type.

    Used when a collection's rules change and by the reconcile/backfill task. Returns the number
    of membership rows changed. Does not commit. A non-smart collection is left untouched.
    """
    if not getattr(collection, "is_smart", False):
        return 0

    target_type = getattr(collection, "target_type", "entry") or "entry"
    model, junction, fk = _membership(target_type)

    rules = collection.smart_rules or {}
    items = session.query(model).filter_by(group_id=group_id).all()
    desired = {i.id for i in items if matches_rules(i, rules, target_type)}
    current = {getattr(row, fk) for row in session.query(junction).filter_by(collection_id=collection.id).all()}

    to_add = desired - current
    to_remove = current - desired
    for item_id in to_add:
        session.add(junction(**{fk: item_id, "collection_id": collection.id, "sort_order": 0}))
    if to_remove:
        session.query(junction).filter(
            junction.collection_id == collection.id,
            getattr(junction, fk).in_(to_remove),
        ).delete(synchronize_session=False)

    return len(to_add) + len(to_remove)
