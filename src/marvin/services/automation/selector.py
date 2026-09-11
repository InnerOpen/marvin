"""Target selector for Flavor B automations — the "FROM" clause.

Normally an automation operates on the single entity its trigger handed it. A ``target`` turns that
around: it runs a *query* to select the entities to operate on, so the automation becomes set-based
(``FROM query WHERE conditions DO actions-per-row``). The query reuses the same fields as the
``find_entries`` agent tool, and its values may be ``$event.*`` templates so a webhook can carry the
query in its payload.

Deliberately **capped** (``MAX_TARGET_ENTITIES``): fanning an action — especially an AI op — over an
unbounded result set is a cost/observability hazard, and there's no per-row execution history yet.
The dry-run preview (see the controller) resolves the same set *without* executing, so an author sees
the count before committing. Unbounded fan-out waits for execution history.

MVP: entity == "entry". Collections/assets can plug in here with their own query builders later.
"""

from .matcher import interpolate

# Hard ceiling on how many entities one automation run will touch. Now that every run + step is
# recorded (automation_executions), a capped batch is fully inspectable, so the cap can be generous —
# but it stays bounded: a runaway query fanning an AI op over the whole workspace is still a real
# cost/rate hazard, and the preview shows the true count so an author sees when it's clipped.
MAX_TARGET_ENTITIES = 250


def resolve_target_entities(session, group_id, target: dict, context: dict, *, cap: int = MAX_TARGET_ENTITIES):
    """Resolve a ``target`` to a list of entities (capped) + the true match count.

    Returns ``(entities, total)`` where ``total`` is the full count before the cap, so callers can
    tell the user "matched 240, acting on the first 25". Raises nothing for an empty match — an empty
    list is a valid (no-op) result. Unknown entity kinds return ``([], 0)``.
    """
    entity = (target or {}).get("entity", "entry")
    if entity != "entry":
        return [], 0

    query = interpolate((target or {}).get("query", {}) or {}, context)
    q = _entries_query(session, group_id, query)
    total = q.count()
    entities = q.order_by(_created_desc()).limit(max(1, min(cap, MAX_TARGET_ENTITIES))).all()
    return entities, total


def entity_ref(entity) -> dict:
    """The lean context/preview shape for a resolved entry (matches the engine's entry context)."""
    etype = entity.entry_type.slug if getattr(entity, "entry_type", None) else None
    return {
        "id": str(entity.id),
        "entry_type": etype,
        "status": entity.status,
        "title": entity.title,
        "slug": entity.slug,
    }


def _created_desc():
    from marvin.db.models.platform.entries import Entries

    return Entries.created_at.desc()


def _entries_query(session, group_id, query: dict):
    """Build an Entries query from a query dict. Same vocabulary as the find_entries tool:
    entry_type (slug), status, text (title contains), has_assets/has_images/has_resources,
    collection (slug or name), metadata ({key: value} equality on metadata_json). Empty/None
    filters are simply not applied — except metadata, where an empty value matches nothing."""
    import sqlalchemy as sa

    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.db.models.platform.entry_resources import EntryResources
    from marvin.db.models.platform.entry_types import EntryTypes

    query = query or {}
    q = session.query(Entries).filter(Entries.group_id == group_id)

    etype = query.get("entry_type")
    if etype:
        q = q.join(EntryTypes, Entries.entry_type_id == EntryTypes.id).filter(EntryTypes.slug == etype)

    status = query.get("status")
    if status:
        q = q.filter(Entries.status == status)

    text = query.get("text") or query.get("query")
    if text:
        q = q.filter(Entries.title.ilike(f"%{text}%"))

    # metadata: {key: value} — equality on metadata_json keys (JSON path, works on SQLite + Postgres).
    # An empty/None value matches NOTHING rather than dropping the filter: a template that resolved
    # to nothing must never widen the query to the whole workspace.
    metadata = query.get("metadata")
    if isinstance(metadata, dict) and metadata:
        for key, value in metadata.items():
            if value is None or value == "":
                return q.filter(sa.false())
            q = q.filter(Entries.metadata_json[key].as_string() == str(value))
    collection = query.get("collection")
    if collection:
        q = (
            q.join(EntryCollections, EntryCollections.entry_id == Entries.id)
            .join(Collections, Collections.id == EntryCollections.collection_id)
            .filter((Collections.slug == collection) | (Collections.name == collection))
        )

    if query.get("has_images") or query.get("has_assets"):
        q = q.join(EntryAssets, EntryAssets.entry_id == Entries.id)
        if query.get("has_images"):
            q = q.join(Assets, Assets.id == EntryAssets.asset_id).filter(Assets.asset_type == "image")

    if query.get("has_resources"):
        q = q.join(EntryResources, EntryResources.entry_id == Entries.id)

    return q.distinct()
