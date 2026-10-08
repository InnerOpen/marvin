"""Built-in core tools — Marvin's read/query surfaces, registered in the tool registry.

These are the exact read/query capabilities the agent previously built as inline controller
closures, moved here as ``handler(ctx, args) -> str`` functions so the internal agent and
MarvinMCP share one definition. Handlers return a JSON string (fed back to the model verbatim
for the agent; parsed to a JSON object for the invoke endpoint).

``compose_entry`` is intentionally NOT here — it stays controller-wired (it has its own endpoint,
SDK method, and MCP tool, and needs the full execution/write-back machinery).
"""

import json

from sqlalchemy import func

from marvin.db.models.platform import EntryCollections
from marvin.db.models.platform.assets import Assets
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_assets import EntryAssets
from marvin.db.models.platform.entry_resources import EntryResources
from marvin.db.models.platform.entry_tags import EntryTags
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.resources import Resources
from marvin.db.models.platform.tags import Tags
from marvin.services.entry_urls import best_entry_url, site_base_url

from ..entity_resolve import resolve_entity_id, resolve_retrieved_sources
from ..operations.base import ROLE_ADMIN
from .base import ToolContext, register_tool


def _asset_public_url(asset) -> str | None:
    """The displayable URL for an asset — same value the admin UI's <img> tags use.

    Mirrors AssetRead.compute_public_url: ask the storage provider to build the URL from the
    storage key (fully-qualified in dev, e.g. http://localhost:8080/assets/<key>), falling back
    to the stored public_url column if the provider is unavailable.
    """
    if getattr(asset, "storage_key", None):
        try:
            from marvin.services.storage.provider_factory import asset_public_url

            return asset_public_url(asset)
        except Exception:
            pass
    return getattr(asset, "public_url", None)


def _link_fields(link) -> dict:
    """The per-attachment (junction-row) metadata — role (e.g. 'hero'), display position, and any
    link-level metadata_json — that lives on EntryAssets/EntryResources, not the entity itself."""
    if link is None:
        return {}
    out = {"role": link.role, "position": link.position}
    if link.metadata_json:
        out["linkMetadata"] = link.metadata_json
    return out


def _serialize_asset(a, link=None) -> dict:
    """One faithful asset shape, used everywhere an entry serializes its media — consistently rich
    (id, type, mime, a real displayable `url`, alt text, dimensions), plus the attachment's
    role/position/metadata when it comes from an entry link."""
    return {
        "id": str(a.id),
        "filename": a.original_filename or a.filename,
        "assetType": a.asset_type,
        "mimeType": a.mime_type,
        "url": _asset_public_url(a),
        "altText": a.alt_text,
        "width": a.width,
        "height": a.height,
        "tags": list(getattr(a, "tag_names", None) or []),
        **_link_fields(link),
    }


def _serialize_resource(r, link=None) -> dict:
    """The FULL resource shape for DETAIL views (get_resource, resources embedded on get_entry) —
    external `url`, description, metadata, plus the attachment's role/position when linked."""
    return {
        "id": str(r.id),
        "name": r.name,
        "slug": r.slug,
        "resourceType": r.resource_type,
        "description": r.description,
        "url": r.url,
        "externalId": r.external_id,
        "metadataJson": r.metadata_json,
        "tags": list(getattr(r, "tag_names", None) or []),
        **_link_fields(link),
    }


def _trash_fields(row) -> dict:
    """``{inTrash, trashedAt}`` for an asset or resource in the Trash (fetched by id or slug), else nothing."""
    when = getattr(row, "trashed_at", None)
    return {"inTrash": True, "trashedAt": when.isoformat()} if when else {}


def _as_uuids(values) -> list:
    """The values that parse as UUIDs (index hits carry string ids)."""
    import uuid as _uuid

    out = []
    for value in values:
        try:
            out.append(_uuid.UUID(str(value)))
        except (ValueError, TypeError):
            pass
    return out


# ── Lean refs for LIST results ────────────────────────────────────────────────
# List tools return minimal previews (identity + what a UI needs to show/link); callers reach for
# the get_* tool when they want the full record. Keeps list payloads out of the agent's context.


def _asset_ref(a) -> dict:
    """Lean asset ref: just enough to render a thumbnail and identify it."""
    return {"id": str(a.id), "assetType": a.asset_type, "url": _asset_public_url(a), "altText": a.alt_text}


def _resource_ref(r) -> dict:
    """Lean resource ref: identity + type + external link, not the full record."""
    return {"id": str(r.id), "name": r.name, "slug": r.slug, "resourceType": r.resource_type, "url": r.url}


def _url_field(entry, site_url: str | None) -> dict:
    """`{"url": ...}` when the entry's page on the site can be resolved, else nothing — a workspace
    that hasn't set up page URLs gets exactly the rows it always did."""
    url = best_entry_url(entry, site_url)
    return {"url": url} if url else {}


def _resolve_collection(ctx: ToolContext, ident: str):
    ident = (ident or "").strip()
    if not ident:
        return None
    col = (
        ctx.session.query(Collections)
        .filter(Collections.group_id == ctx.group_id)
        .filter((Collections.slug == ident) | (Collections.name.ilike(ident)))
        .first()
    )
    if col:
        return col
    try:
        import uuid as _uuid

        col = ctx.session.get(Collections, _uuid.UUID(ident))
    except (ValueError, TypeError):
        return None
    return col if (col and col.group_id == ctx.group_id) else None


@register_tool(
    name="search_content",
    description="Semantic search over workspace content (entries, resources, and assets). Returns the most relevant snippets with their entity ids/titles, and (for entry hits) lean image refs so results can show thumbnails. The index gives relevance + ids; call get_entry for the full record. Use this to ground answers.",  # noqa: E501
    input_schema={"type": "object", "properties": {"query": {"type": "string", "description": "what to search for"}}, "required": ["query"]},
)
def search_content(ctx: ToolContext, args: dict) -> str:
    import uuid as _uuid

    query = str(args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "query is required"})
    if ctx.provider is None:
        return json.dumps({"error": "semantic search unavailable (no AI provider configured)"})
    from marvin.core.config import get_app_settings
    from marvin.services.ai.context import ContextBuilder
    from marvin.services.ai.embeddings import default_embedding_model
    from marvin.services.ai.embeddings_registry import indexable_types

    emb_model = default_embedding_model(ctx.provider.provider_type)
    if not emb_model:
        return json.dumps({"error": "semantic search unavailable (no embedding model configured)"})
    top_k = getattr(get_app_settings(), "AI_RAG_TOP_K", 5)
    built = (
        ContextBuilder(ctx.session, ctx.group_id)
        .with_semantic_search(query, ctx.provider, emb_model, limit=top_k, entity_types=indexable_types())
        .build()
    )
    retrieved = built.retrieved or []
    sources = resolve_retrieved_sources(ctx.session, retrieved)
    results = []
    for i, chunk in enumerate(retrieved):
        src = sources[i] if i < len(sources) else {}
        text = chunk.get("text") or chunk.get("content") or ""
        results.append(
            {
                "title": src.get("title"),
                "entityType": src.get("entity_type"),
                "entityId": src.get("entity_id"),
                "snippet": text[:400],
                "score": src.get("score"),
            }
        )
    # The index only knows relevance + ids. Hydrate lean image refs for entry hits from the DB
    # (source of truth) so search results can show thumbnails too — fresh even as the index lags.
    entry_uuids = []
    for r in results:
        if r["entityType"] == "entry" and r["entityId"]:
            try:
                entry_uuids.append(_uuid.UUID(r["entityId"]))
            except (ValueError, TypeError):
                pass
    images_by_entry: dict = {}
    urls_by_entry: dict = {}
    trashed: set[str] = set()
    if entry_uuids:
        for eid, a in (
            ctx.session.query(EntryAssets.entry_id, Assets)
            .join(Assets, Assets.id == EntryAssets.asset_id)
            .filter(EntryAssets.entry_id.in_(entry_uuids), Assets.asset_type == "image", Assets.trashed_at.is_(None))
            .order_by(EntryAssets.position)
            .all()
        ):
            images_by_entry.setdefault(str(eid), []).append(_asset_ref(a))
        site_url = site_base_url(ctx.session, ctx.group_id)
        for e in ctx.session.query(Entries).filter(Entries.group_id == ctx.group_id, Entries.id.in_(entry_uuids)).all():
            urls_by_entry[str(e.id)] = _url_field(e, site_url)
            if e.status == "trashed":  # the index drops it on entry_trashed; don't show it meanwhile
                trashed.add(str(e.id))
    # Assets and resources in the Trash too (the index drops them on asset_trashed / resource_trashed).
    for kind, model in (("asset", Assets), ("resource", Resources)):
        ids = [r["entityId"] for r in results if r["entityType"] == kind and r["entityId"]]
        if ids:
            rows = ctx.session.query(model.id).filter(model.group_id == ctx.group_id, model.id.in_(_as_uuids(ids)), model.trashed_at.isnot(None))
            trashed.update(str(row[0]) for row in rows)
    results = [r for r in results if not (r["entityType"] in ("entry", "asset", "resource") and r["entityId"] in trashed)]
    for r in results:
        r["assets"] = images_by_entry.get(r["entityId"], []) if r["entityType"] == "entry" else []
        if r["entityType"] == "entry":
            r.update(urls_by_entry.get(r["entityId"], {}))
    return json.dumps({"results": results, "count": len(results)})


# Rows stay lean, so a larger page is affordable — enough to compare a field across a whole type in
# one call instead of opening each entry.
FIND_ENTRIES_MAX_ROWS = 200
FIND_ENTRIES_MAX_FIELDS = 8

from marvin.services.entries.query import WHERE_OPS  # noqa: E402 — the tool schema lists the shared ops


@register_tool(
    name="find_entries",
    description=(
        "Find entries matching a description and return a lean list. Filters (all optional): entry_type; status = the "
        "PUBLISH status (inbox, draft, needs_review, approved, published, archived — never a field's value); fields = exact "
        "match on the entry type's own fields {field_key: value}; where = comparisons on fields [{field, op, value}] with op "
        "eq|neq|in|contains|exists|missing|gt|gte|lt|lte (number-like text such as '$1,170' compares as 1170); query = "
        "title/slug contains; tags; collection; has_images / has_assets / has_resources; created_/updated_/published_ "
        "after|before (ISO dates). Field keys differ per type and per workspace — take them from get_entry_type. "
        "sort = {by: title|created_at|updated_at|published_at|<field_key>, direction: asc|desc} (fields sort numerically when "
        "number-like). group_by = a field key (or publish_status / entry_type) → counts per value over the whole match. "
        "include_fields / include_metadata = keys whose values to put on each row, so you can compare many entries in one "
        "call instead of get_entry on each. Returns `count` (true total), `returned`, rows (default 10, max 200; use offset "
        "to page) and `groups` when grouped. Use `count` to answer 'how many'. A row's `url`, when present, is the entry's "
        "page on the workspace's site — use it to link the entry."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entry_type": {"type": "string"},
            "status": {"type": "string", "description": "publish status: inbox | draft | needs_review | approved | published | archived"},
            "fields": {"type": "object", "description": "exact match on the entry type's own fields, {field_key: value}"},
            "where": {
                "type": "array",
                "description": "field comparisons; field = a field key or metadata.<key>",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "op": {"type": "string", "enum": list(WHERE_OPS)},
                        "value": {},
                    },
                    "required": ["field"],
                },
            },
            "query": {"type": "string", "description": "title or slug contains"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "only entries carrying ANY of these tags (slug or name) — exhaustive, not ranked",
            },
            "collection": {"type": "string", "description": "only entries in this collection (slug or name)"},
            "has_images": {"type": "boolean", "description": "only entries that have an image asset"},
            "has_assets": {"type": "boolean", "description": "only entries that have any attached asset"},
            "has_resources": {"type": "boolean", "description": "only entries that have a linked resource"},
            "created_after": {"type": "string"},
            "created_before": {"type": "string"},
            "updated_after": {"type": "string"},
            "updated_before": {"type": "string"},
            "published_after": {"type": "string"},
            "published_before": {"type": "string"},
            "sort": {
                "type": "object",
                "properties": {"by": {"type": "string"}, "direction": {"type": "string", "enum": ["asc", "desc"]}},
            },
            "group_by": {"type": "string"},
            "include_fields": {"type": "array", "items": {"type": "string"}, "description": "field keys whose values to include on each row"},
            "include_metadata": {"type": "array", "items": {"type": "string"}, "description": "metadata keys whose values to include on each row"},
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
        },
    },
)
def find_entries(ctx: ToolContext, args: dict) -> str:
    from marvin.services.entries.query import run as run_entry_query

    limit = max(1, min(int(args.get("limit") or 10), FIND_ENTRIES_MAX_ROWS))
    result = run_entry_query(ctx.session, ctx.group_id, args, limit=limit, offset=int(args.get("offset") or 0))
    if result.note:
        return json.dumps({"count": 0, "entries": [], "note": result.note})
    rows, total = result.rows, result.total
    include = [str(k) for k in (args.get("include_fields") or []) if str(k).strip()][:FIND_ENTRIES_MAX_FIELDS]
    include_meta = [str(k) for k in (args.get("include_metadata") or []) if str(k).strip()][:FIND_ENTRIES_MAX_FIELDS]
    # This is a LIST, not a detail view: keep rows LEAN to avoid bloating the agent's context.
    # Enough for the caller/UI to show thumbnails and link out — image-ready asset refs (with a
    # real `url` for the thumbnail strip) and lightweight resource refs (name/type/url). For the
    # full graph (descriptions, metadata, junction roles, timestamps) the caller uses get_entry.
    entry_ids = [e.id for e in rows]
    assets_by_entry: dict = {}
    resources_by_entry: dict = {}
    tags_by_entry: dict = {}
    if entry_ids:
        for eid, slug in (
            ctx.session.query(EntryTags.entry_id, Tags.slug).join(Tags, Tags.id == EntryTags.tag_id).filter(EntryTags.entry_id.in_(entry_ids)).all()
        ):
            tags_by_entry.setdefault(eid, []).append(slug)
        for eid, a in (
            ctx.session.query(EntryAssets.entry_id, Assets)
            .join(Assets, Assets.id == EntryAssets.asset_id)
            .filter(EntryAssets.entry_id.in_(entry_ids), Assets.trashed_at.is_(None))
            .order_by(EntryAssets.position)
            .all()
        ):
            assets_by_entry.setdefault(eid, []).append(_asset_ref(a))
        for eid, r in (
            ctx.session.query(EntryResources.entry_id, Resources)
            .join(Resources, Resources.id == EntryResources.resource_id)
            .filter(EntryResources.entry_id.in_(entry_ids), Resources.trashed_at.is_(None))
            .order_by(EntryResources.position)
            .all()
        ):
            resources_by_entry.setdefault(eid, []).append(_resource_ref(r))
    site_url = site_base_url(ctx.session, ctx.group_id) if rows else None
    out = [
        {
            "id": str(e.id),
            "title": e.title,
            "slug": e.slug,
            "status": e.status,
            "entryType": e.entry_type.slug if e.entry_type else None,
            **_url_field(e, site_url),
            "assets": assets_by_entry.get(e.id, []),
            "resources": resources_by_entry.get(e.id, []),
            "tags": tags_by_entry.get(e.id, []),
            **({"fields": {k: (e.data_json or {}).get(k) for k in include}} if include else {}),
            **({"metadata": {k: (e.metadata_json or {}).get(k) for k in include_meta}} if include_meta else {}),
        }
        for e in rows
    ]
    # `count` is the full match count; `entries` is a page capped at `limit`.
    payload: dict = {"entries": out, "count": total, "returned": len(out)}
    if result.groups is not None:
        payload["groups"] = result.groups
    if result.scan_capped:
        payload["note"] = "matched more entries than can be compared in one pass; narrow the filters for exact counts"
    if result.unknown_ops:
        payload["ignored_ops"] = result.unknown_ops
    return json.dumps(payload)


@register_tool(
    name="get_entry",
    description="Get one entry COMPLETE by id or slug: all fields (data, summary, description, timestamps) plus fully-hydrated attachments — assets (each with a real displayable `url`, assetType, altText, dimensions, and attachment role/position), linked resources (with their `url` + role), collection membership, and tag slugs. Use the asset `url` to reference/show an image; never invent an image URL. The entry's own `url`, when present, is its page on the workspace's site — use it to link the entry.",  # noqa: E501
    input_schema={"type": "object", "properties": {"id_or_slug": {"type": "string"}}, "required": ["id_or_slug"]},
)
def get_entry(ctx: ToolContext, args: dict) -> str:
    ident = str(args.get("id_or_slug") or args.get("id") or args.get("slug") or "").strip()
    if not ident:
        return json.dumps({"error": "id_or_slug is required"})
    eid = resolve_entity_id(ctx.session, ctx.group_id, "entry", ident)
    # resolve_entity_id returns a UUID when it resolves (a real id or a matched slug) and the raw
    # input otherwise. A non-UUID here means "no such slug" — don't feed it to session.get (which
    # would raise on UUID coercion); report not-found.
    import uuid as _uuid

    entry = ctx.session.get(Entries, eid) if isinstance(eid, _uuid.UUID) else None
    if not entry or entry.group_id != ctx.group_id:
        return json.dumps({"error": f"entry '{ident}' not found"})
    # Return the FULL entry — every scalar field plus fully-hydrated attachments (each asset /
    # resource carries its entity data AND the junction row's role/position/metadata), so the model
    # never needs a follow-up tool to reason about media, references, or membership.
    asset_links = (
        ctx.session.query(EntryAssets, Assets)
        .join(Assets, Assets.id == EntryAssets.asset_id)
        .filter(EntryAssets.entry_id == entry.id, Assets.trashed_at.is_(None))  # the Trash is out of sight
        .order_by(EntryAssets.position)
        .all()
    )
    resource_links = (
        ctx.session.query(EntryResources, Resources)
        .join(Resources, Resources.id == EntryResources.resource_id)
        .filter(EntryResources.entry_id == entry.id, Resources.trashed_at.is_(None))
        .order_by(EntryResources.position)
        .all()
    )
    collections = (
        ctx.session.query(Collections)
        .join(EntryCollections, EntryCollections.collection_id == Collections.id)
        .filter(EntryCollections.entry_id == entry.id)
        .all()
    )
    return json.dumps(
        {
            "id": str(entry.id),
            "title": entry.title,
            "slug": entry.slug,
            "status": entry.status,
            "summary": entry.summary,
            "description": entry.description,
            "entryType": entry.entry_type.slug if entry.entry_type else None,
            **_url_field(entry, site_base_url(ctx.session, ctx.group_id)),
            "data": entry.data_json,
            "metadataJson": entry.metadata_json,
            "publishedAt": entry.published_at.isoformat() if entry.published_at else None,
            "createdAt": entry.created_at.isoformat() if getattr(entry, "created_at", None) else None,
            "updatedAt": entry.update_at.isoformat() if getattr(entry, "update_at", None) else None,
            "createdBy": str(entry.created_by) if entry.created_by else None,
            "assets": [_serialize_asset(a, link) for link, a in asset_links],
            "resources": [_serialize_resource(r, link) for link, r in resource_links],
            "collections": [{"slug": c.slug, "name": c.name} for c in collections],
            "tags": list(entry.tag_names),
        }
    )


@register_tool(
    name="get_collection",
    description="Get one collection in full by name, slug, or id: its description, smart/system/public flags, icon/color, entryCount, and smart-collection rules. Use for questions about a specific collection.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {"id_or_slug": {"type": "string", "description": "collection name, slug, or id"}},
        "required": ["id_or_slug"],
    },
)
def get_collection(ctx: ToolContext, args: dict) -> str:
    ident = str(args.get("id_or_slug") or args.get("collection") or args.get("slug") or "").strip()
    col = _resolve_collection(ctx, ident)
    if not col:
        return json.dumps({"error": f"collection '{ident}' not found — pass its name, slug, or id"})
    from marvin.services.entries.trash import collection_entries_filter

    count = (
        ctx.session.query(func.count(EntryCollections.entry_id))
        .join(Entries, Entries.id == EntryCollections.entry_id)
        .filter(EntryCollections.collection_id == col.id, collection_entries_filter(col))
        .scalar()
    ) or 0
    return json.dumps(
        {
            "id": str(col.id),
            "name": col.name,
            "slug": col.slug,
            "description": col.description,
            "isSmart": col.is_smart,
            "isSystem": col.is_system,
            "isPublic": col.is_public,
            "icon": col.icon,
            "color": col.color,
            "entryCount": count,
            "smartRules": col.smart_rules,
            "metadataJson": col.metadata_json,
        }
    )


@register_tool(
    name="get_resource",
    description="Get one reusable resource in full by slug or id: its name, resourceType, description, url, externalId, and metadataJson. Use for questions about a specific resource (material, tool, supplier, …).",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {"id_or_slug": {"type": "string", "description": "resource slug or id"}},
        "required": ["id_or_slug"],
    },
)
def get_resource(ctx: ToolContext, args: dict) -> str:
    import uuid as _uuid

    ident = str(args.get("id_or_slug") or args.get("id") or args.get("slug") or "").strip()
    if not ident:
        return json.dumps({"error": "id_or_slug is required"})
    rid = resolve_entity_id(ctx.session, ctx.group_id, "resource", ident)
    resource = ctx.session.get(Resources, rid) if isinstance(rid, _uuid.UUID) else None
    if not resource or resource.group_id != ctx.group_id:
        return json.dumps({"error": f"resource '{ident}' not found"})
    return json.dumps({**_serialize_resource(resource), **_trash_fields(resource)})


@register_tool(
    name="get_entry_type",
    description="Get one entry type by slug or id, including its full field schema (schema) and authoring recipe (recipe). The field schema is what compose fills — fetch this before composing an entry of that type.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {"id_or_slug": {"type": "string", "description": "entry type slug or id"}},
        "required": ["id_or_slug"],
    },
)
def get_entry_type(ctx: ToolContext, args: dict) -> str:
    import uuid as _uuid

    ident = str(args.get("id_or_slug") or args.get("id") or args.get("slug") or "").strip()
    if not ident:
        return json.dumps({"error": "id_or_slug is required"})
    # Resolve by slug (workspace or system type), then by id — mirrors compose-entry's lookup.
    et = (
        ctx.session.query(EntryTypes)
        .filter(EntryTypes.slug == ident)
        .filter((EntryTypes.group_id == ctx.group_id) | (EntryTypes.group_id.is_(None)))
        .first()
    )
    if not et:
        try:
            candidate = ctx.session.get(EntryTypes, _uuid.UUID(ident))
            if candidate and candidate.group_id in (None, ctx.group_id):
                et = candidate
        except (ValueError, TypeError):
            et = None
    if not et:
        return json.dumps({"error": f"entry type '{ident}' not found"})
    fields = [f.get("key") for f in (et.schema_json or {}).get("fields", []) if isinstance(f, dict)]
    return json.dumps(
        {
            "id": str(et.id),
            "name": et.name,
            "slug": et.slug,
            "description": et.description,
            "isSystem": et.is_system,
            "isRendered": et.is_rendered,
            "icon": et.icon,
            "color": et.color,
            "fields": fields,
            "schema": et.schema_json,
            "recipe": et.recipe_json,
            **({"pageUrlPattern": et.page_url_pattern} if et.page_url_pattern else {}),
        }
    )


@register_tool(
    name="list_collections",
    description="List the workspace's collections with their entryCount (name, slug, smart/system flags). Use for questions about collections, how content is organized, or how many entries a collection holds.",  # noqa: E501
    input_schema={"type": "object", "properties": {}},
)
def list_collections(ctx: ToolContext, _args: dict) -> str:
    from marvin.services.entries.trash import TRASHED, is_trash_collection, not_trashed

    rows = ctx.session.query(Collections).filter(Collections.group_id == ctx.group_id).all()

    def _counts(*filters) -> dict:
        return dict(
            ctx.session.query(EntryCollections.collection_id, func.count(EntryCollections.entry_id))
            .join(Collections, Collections.id == EntryCollections.collection_id)
            .join(Entries, Entries.id == EntryCollections.entry_id)
            .filter(Collections.group_id == ctx.group_id, *filters)
            .group_by(EntryCollections.collection_id)
            .all()
        )

    counts, in_trash = _counts(not_trashed()), _counts(Entries.status == TRASHED)
    out = [
        {
            "id": str(c.id),
            "name": c.name,
            "slug": c.slug,
            "isSmart": c.is_smart,
            "isSystem": c.is_system,
            "entryCount": (in_trash if is_trash_collection(c) else counts).get(c.id, 0),
        }
        for c in rows
    ]
    return json.dumps({"collections": out, "count": len(out)})


@register_tool(
    name="get_collection_entries",
    description="List the entries in one collection by name or slug (e.g. 'inbox', 'drafts'). Returns each entry and the total count. Use this for 'what/how many is in <collection>' — collections like Inbox/Drafts are how entries are organized, not entry statuses.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {"collection": {"type": "string", "description": "collection name or slug"}},
        "required": ["collection"],
    },
)
def get_collection_entries(ctx: ToolContext, args: dict) -> str:
    col = _resolve_collection(ctx, str(args.get("collection") or args.get("id_or_slug") or args.get("slug") or ""))
    if not col:
        return json.dumps({"error": "collection not found — pass its name or slug (e.g. 'inbox')"})
    from marvin.services.entries.trash import collection_entries_filter

    rows = (
        ctx.session.query(Entries)
        .join(EntryCollections, EntryCollections.entry_id == Entries.id)
        .filter(EntryCollections.collection_id == col.id, collection_entries_filter(col))
        .all()
    )
    site_url = site_base_url(ctx.session, ctx.group_id) if rows else None
    out = [
        {
            "id": str(e.id),
            "title": e.title,
            "slug": e.slug,
            "status": e.status,
            "entryType": e.entry_type.slug if e.entry_type else None,
            **_url_field(e, site_url),
        }
        for e in rows
    ]
    return json.dumps({"collection": col.slug, "entries": out, "count": len(out)})


@register_tool(
    name="list_tags",
    description="List the workspace's tags — the one shared vocabulary across entries, assets, and resources — with usage on each surface (name, slug, entryCount, assetCount, resourceCount). THIS is the tool for 'what tags exist / are available'; do not use search_content for that.",  # noqa: E501
    input_schema={"type": "object", "properties": {}},
)
def list_tags(ctx: ToolContext, _args: dict) -> str:
    from marvin.db.models.platform.asset_tags import AssetTags
    from marvin.db.models.platform.resource_tags import ResourceTags
    from marvin.services.entries.trash import not_trashed

    def _counts(junction, fk, *, entries: bool = False, item=None):
        q = ctx.session.query(junction.tag_id, func.count(getattr(junction, fk))).join(Tags, Tags.id == junction.tag_id)
        if entries:  # an entry in the Trash doesn't count as using the tag
            q = q.join(Entries, Entries.id == junction.entry_id).filter(not_trashed())
        if item is not None:  # nor does an asset or resource in the Trash
            q = q.join(item, item.id == getattr(junction, fk)).filter(item.trashed_at.is_(None))
        return dict(q.filter(Tags.group_id == ctx.group_id).group_by(junction.tag_id).all())

    rows = ctx.session.query(Tags).filter(Tags.group_id == ctx.group_id).all()
    ec = _counts(EntryTags, "entry_id", entries=True)
    ac, rc = _counts(AssetTags, "asset_id", item=Assets), _counts(ResourceTags, "resource_id", item=Resources)
    out = [
        {
            "id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "entryCount": ec.get(t.id, 0),
            "assetCount": ac.get(t.id, 0),
            "resourceCount": rc.get(t.id, 0),
        }
        for t in rows
    ]
    return json.dumps({"tags": out, "count": len(out)})


# Filters list_assets and list_resources share (services/item_query.py — the same query trash_entries' `match`
# and attach_tag's `filter` select by).
_ITEM_LIST_FILTERS = {
    "collection": {"type": "string", "description": "only items in this collection (slug or name)"},
    "unattached": {"type": "boolean", "description": "true: only items attached to no entry; false: only attached ones"},
    "created_after": {"type": "string", "description": "ISO date — created on or after"},
    "created_before": {"type": "string", "description": "ISO date — created before"},
}


@register_tool(
    name="list_resources",
    description="List the workspace's reusable resources (materials, tools, suppliers, …), optionally filtered by resource_type, tags, collection, whether they are attached to any entry, and when they were created. Returns `count` (true total) plus a sample. Use for questions about resources, or 'all resources with tag X'.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {
            "resource_type": {"type": "string"},
            "query": {"type": "string", "description": "name/slug substring"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "only resources carrying ANY of these tags (slug or name) — exhaustive, not ranked",
            },
            **_ITEM_LIST_FILTERS,
            "limit": {"type": "integer"},
        },
    },
)
def list_resources(ctx: ToolContext, args: dict) -> str:
    from marvin.services import item_query

    result = item_query.run(ctx.session, ctx.group_id, "resource", args, limit=min(int(args.get("limit") or 20), 50))
    if result.note:
        return json.dumps({"resources": [], "count": 0, "returned": 0, "note": result.note})
    out = [_resource_ref(r) for r in result.rows]  # LIST → lean; get_resource returns the full record
    return json.dumps({"resources": out, "count": result.total, "returned": len(out)})


@register_tool(
    name="list_entry_types",
    description="List the workspace's entry types and their field keys. Use before composing to pick a type.",
    input_schema={"type": "object", "properties": {}},
)
def list_entry_types(ctx: ToolContext, _args: dict) -> str:
    rows = ctx.session.query(EntryTypes).filter((EntryTypes.group_id == ctx.group_id) | (EntryTypes.group_id.is_(None))).all()
    out = []
    for t in rows:
        fields = [f.get("key") for f in (t.schema_json or {}).get("fields", []) if isinstance(f, dict)]
        out.append({"slug": t.slug, "name": t.name, "fields": fields})
    return json.dumps({"entryTypes": out, "count": len(out)})


@register_tool(
    name="list_assets",
    description="List the workspace's assets (images, files), optionally filtered by asset_type (e.g. 'image'), a filename substring (query), tags, collection, whether they are attached to any entry, and when they were created. Returns `count` (true total) plus a lightweight sample — each with a real displayable `url` for thumbnails; call get_asset for the full record. Use tags for 'all assets with tag X' — exhaustive, not a ranked search.",  # noqa: E501
    input_schema={
        "type": "object",
        "properties": {
            "asset_type": {"type": "string", "description": "e.g. 'image', 'document'"},
            "query": {"type": "string", "description": "filename/name substring"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "only assets carrying ANY of these tags (slug or name) — exhaustive, not ranked",
            },
            **_ITEM_LIST_FILTERS,
            "limit": {"type": "integer"},
        },
    },
)
def list_assets(ctx: ToolContext, args: dict) -> str:
    from marvin.services import item_query

    result = item_query.run(ctx.session, ctx.group_id, "asset", args, limit=min(int(args.get("limit") or 20), 50))
    if result.note:
        return json.dumps({"assets": [], "count": 0, "returned": 0, "note": result.note})
    out = [_asset_ref(a) for a in result.rows]  # LIST → lean; get_asset returns the full record
    return json.dumps({"assets": out, "count": result.total, "returned": len(out)})


@register_tool(
    name="get_asset",
    description="Get one asset COMPLETE by slug or id: filename, type, mime, dimensions, file size, a real displayable `url`, alt text, description, and metadata. Use the `url` to show/reference the image; never invent one.",  # noqa: E501
    input_schema={"type": "object", "properties": {"id_or_slug": {"type": "string", "description": "asset slug or id"}}, "required": ["id_or_slug"]},
)
def get_asset(ctx: ToolContext, args: dict) -> str:
    import uuid as _uuid

    ident = str(args.get("id_or_slug") or args.get("id") or args.get("slug") or "").strip()
    if not ident:
        return json.dumps({"error": "id_or_slug is required"})
    aid = resolve_entity_id(ctx.session, ctx.group_id, "asset", ident)
    a = ctx.session.get(Assets, aid) if isinstance(aid, _uuid.UUID) else None
    if not a or a.group_id != ctx.group_id:
        return json.dumps({"error": f"asset '{ident}' not found"})
    return json.dumps(
        {
            "id": str(a.id),
            "slug": a.slug,
            "name": a.name,
            "filename": a.original_filename or a.filename,
            "extension": a.extension,
            "assetType": a.asset_type,
            "mimeType": a.mime_type,
            "fileSize": a.file_size,
            "width": a.width,
            "height": a.height,
            "orientation": a.orientation,
            "url": _asset_public_url(a),
            "altText": a.alt_text,
            "description": a.description,
            "metadataJson": a.metadata_json,
            "storageProvider": a.storage_provider,
            "createdAt": a.created_at.isoformat() if getattr(a, "created_at", None) else None,
            "updatedAt": a.update_at.isoformat() if getattr(a, "update_at", None) else None,
            "uploadedBy": str(a.uploaded_by) if a.uploaded_by else None,
            **_trash_fields(a),
        }
    )


def _workflow_ref(auto) -> dict:
    return {"name": auto.name, "slug": auto.slug, "enabled": bool(auto.enabled), "trigger": auto.trigger_type}


def _find_workflow(session, group_id, ref: str):
    """Match a workflow by slug, name (case-insensitive) or id; None when nothing matches."""
    import uuid

    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    q = session.query(WorkspaceAutomationModel).filter_by(group_id=group_id)
    low = ref.lower()
    auto = q.filter(func.lower(WorkspaceAutomationModel.slug) == low).first() or q.filter(func.lower(WorkspaceAutomationModel.name) == low).first()
    if auto is None:
        try:
            cand = session.get(WorkspaceAutomationModel, uuid.UUID(ref))
            if cand and cand.group_id == group_id:
                auto = cand
        except (ValueError, TypeError):
            pass
    return auto


@register_tool(
    name="list_workflows",
    description=(
        "List this workspace's automations (workflows): name, slug, enabled, trigger type. Call this before "
        "run_workflow when the user names a workflow loosely, to get its exact slug; use for 'what workflows "
        "exist' or 'is workflow X on'."
    ),
    input_schema={"type": "object", "properties": {}},
    min_role=ROLE_ADMIN,  # workflows are workspace settings; GET /automations is ADMIN too
)
def list_workflows(ctx: ToolContext, _args: dict) -> str:
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    rows = ctx.session.query(WorkspaceAutomationModel).filter_by(group_id=ctx.group_id).order_by(WorkspaceAutomationModel.name).all()
    return json.dumps({"workflows": [_workflow_ref(a) for a in rows], "count": len(rows)})


@register_tool(
    name="run_workflow",
    description=(
        "Run one of this workspace's automations (workflows) by slug, name, or id — e.g. to rebuild "
        "the site, reindex search, or run a content pipeline. Runs it now, skipping the workflow's "
        "trigger/condition gates (like pressing Run). Returns whether it completed. Names match "
        "case-insensitively; when nothing matches the error lists the workflows that exist — pick the "
        "right one (or ask the user) rather than guessing again."
    ),
    input_schema={
        "type": "object",
        "properties": {"workflow": {"type": "string", "description": "workflow slug, name, or id"}},
        "required": ["workflow"],
    },
    # ADMIN, like POST /automations/{id}/run: a workflow runs with its definer's role and can call
    # integrations and webhooks with the workspace's credentials.
    min_role=ROLE_ADMIN,
    read_only=False,
)
def run_workflow(ctx: ToolContext, args: dict) -> str:
    """Let the agent (or an MCP host) trigger a Flavor B workflow from chat — the 'Chat' trigger."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation.engine import run_automation_now

    ref = str(args.get("workflow") or "").strip()
    if not ref:
        return json.dumps({"error": "workflow (slug, name, or id) is required"})

    auto = _find_workflow(ctx.session, ctx.group_id, ref)
    if not auto:
        rows = ctx.session.query(WorkspaceAutomationModel).filter_by(group_id=ctx.group_id).order_by(WorkspaceAutomationModel.name).all()
        return json.dumps({"error": f"no workflow '{ref}' in this workspace", "available": [_workflow_ref(a) for a in rows]})
    if not auto.enabled:
        return json.dumps({"error": f"workflow '{auto.slug}' is disabled"})

    from marvin.services.automation.recorder import ExecutionRecorder

    user_id = ctx.user.id if ctx.user else None
    # Recorded like the Run button, so a run started from chat or MCP shows under the workflow's Runs.
    res = run_automation_now(
        ctx.session,
        ctx.group_id,
        auto,
        user_id=user_id,
        logger=ctx.logger,
        recorder=ExecutionRecorder(ctx.session, ctx.group_id),
        trigger_kind="chat",
    )
    return json.dumps({"workflow": auto.slug, "ok": res.get("ok"), "result": res.get("result")})
