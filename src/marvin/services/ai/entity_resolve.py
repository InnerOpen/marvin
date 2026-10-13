"""Shared entity-resolution helpers for the AI controller and tool handlers.

Both the operations controller and the core tool handlers need to (a) accept a UUID *or*
a slug for an entity id (MCP/CLI callers work in slugs) and (b) map retrieved RAG chunks
back to their entity + resolved title for citations. These live here so both import them
rather than reaching into the controller.
"""

import uuid as _uuid


def resolve_entity_id(session, group_id, entity_type: str | None, entity_id):
    """Accept a UUID or a slug for entity_id so MCP/CLI callers can work in slugs.

    Returns the entity's UUID (resolving a slug for entry/asset/resource within this
    workspace), or the input unchanged when it's already a UUID or can't be resolved
    (downstream loaders then 404 exactly as before). An entry can also be named by its exact
    title (case-insensitive) when exactly one entry in the workspace has it — a model given a
    list of titles often passes the title back instead of the slug next to it.
    """
    if not entity_id:
        return entity_id

    try:
        return _uuid.UUID(str(entity_id))  # already a UUID — normalize
    except (ValueError, TypeError):
        pass

    model = None
    if entity_type == "entry":
        from marvin.db.models.platform.entries import Entries

        model = Entries
    elif entity_type == "resource":
        from marvin.db.models.platform.resources import Resources

        model = Resources
    elif entity_type == "asset":
        from marvin.db.models.platform.assets import Assets

        model = Assets
    if model is None:
        return entity_id

    row = session.query(model).filter_by(group_id=group_id, slug=str(entity_id)).first()
    if row:
        return row.id
    if model.__name__ == "Entries":
        from sqlalchemy import func

        titled = session.query(model.id).filter(model.group_id == group_id, func.lower(model.title) == str(entity_id).strip().lower()).limit(2).all()
        if len(titled) == 1:
            return titled[0][0]
    return entity_id


def resolve_retrieved_sources(session, retrieved: list[dict]) -> list[dict]:
    """Map retrieved chunks (in citation order) to their entity + resolved title.

    The LLM cites sources by their 1-based [n] index, which aligns with this ordered list,
    so the UI can turn each citation into a link. Titles are looked up in bulk per type.
    """
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.resources import Resources

    entry_ids = {c["entity_id"] for c in retrieved if c.get("entity_type") == "entry"}
    resource_ids = {c["entity_id"] for c in retrieved if c.get("entity_type") == "resource"}
    asset_ids = {c["entity_id"] for c in retrieved if c.get("entity_type") == "asset"}
    titles: dict[tuple[str, str], str] = {}
    if entry_ids:
        for e in session.query(Entries).filter(Entries.id.in_(entry_ids)).all():
            titles[("entry", str(e.id))] = e.title or "Untitled entry"
    if resource_ids:
        for r in session.query(Resources).filter(Resources.id.in_(resource_ids)).all():
            titles[("resource", str(r.id))] = r.name or "Untitled resource"
    if asset_ids:
        for a in session.query(Assets).filter(Assets.id.in_(asset_ids)).all():
            titles[("asset", str(a.id))] = a.name or "Untitled asset"

    sources: list[dict] = []
    for i, c in enumerate(retrieved):
        et = c.get("entity_type")
        eid = str(c.get("entity_id"))
        sources.append(
            {
                "index": i + 1,
                "entity_type": et,
                "entity_id": eid,
                "title": titles.get((et or "", eid), f"{et} {eid[:8]}"),
                "score": c.get("score"),
            }
        )
    return sources
