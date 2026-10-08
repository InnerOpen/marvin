"""Built-in ACTION tools — the registry's write capabilities (deterministic entry-linking).

Everything else in the registry is read-only; these mutate. They go through EntryService so each
mutation and its event fires correctly (entry_resource_attached / entry_tag_attached /
asset_attached_to_entry / entry_added_to_collection …) and automations can react. Gated at EDITOR,
read_only=False: they act on any entry, asset or collection, which only an EDITOR may change (an AUTHOR
changes only their own drafts, and these tools don't check ownership). Because they're registry tools they project to MarvinMCP automatically
(marvin_attach_resource, marvin_attach_tag, …) and bind in-process to the agent — one definition,
both surfaces.

This is the "deterministic manipulation" surface: attach/detach a *specific* existing (or
find-or-created) tag / resource / asset / collection to an entry, complementing the AI-authoring
path (compose_entry / generate-tags) which decides links for you.
"""

import json
from types import SimpleNamespace

from ..entity_resolve import resolve_entity_id
from ..operations.base import ROLE_EDITOR
from .base import ToolContext, register_tool
from .bulk_writes import BulkWrite

_ENTRY_ARG = {"type": "string", "description": "the entry by slug or id"}


def _service(ctx: ToolContext):
    from marvin.services.entries import EntryService

    return EntryService(ctx.session, ctx.group_id, actor_id=getattr(ctx.user, "id", None))


def _entry_link(ctx: ToolContext, args: dict, *, method: str, ref_key: str, role: bool = False) -> str:
    """Shared body for the entry-link tools: resolve the entry, call the EntryService method with the
    ref (+ optional role), map the idempotent result to JSON."""
    entry_id = resolve_entity_id(ctx.session, ctx.group_id, "entry", args.get("entry"))
    ref = str(args.get(ref_key) or "")
    kwargs = {"role": args["role"]} if role and args.get("role") else {}
    result = getattr(_service(ctx), method)(entry_id, ref, **kwargs)
    if result is None:
        return json.dumps({"error": f"entry or {ref_key} not found in this workspace — check the entry slug/id and the {ref_key}"})
    return json.dumps({"entry": str(args.get("entry")), ref_key: ref, "result": result})


def _link_schema(ref_key: str, ref_desc: str, *, role: bool = False) -> dict:
    props = {"entry": _ENTRY_ARG, ref_key: {"type": "string", "description": ref_desc}}
    if role:
        props["role"] = {"type": "string", "description": "optional role/label for this link (e.g. 'hero', 'primary')"}
    return {"type": "object", "properties": props, "required": ["entry", ref_key]}


# ── Resources ─────────────────────────────────────────────────────────────────
@register_tool(
    name="attach_resource",
    description="Attach a reusable resource (material, technique, supplier, …) to an entry. Idempotent. Identify the entry by slug/id and the resource by slug/name/id.",  # noqa: E501
    input_schema=_link_schema("resource", "the resource by slug, name, or id", role=True),
    min_role=ROLE_EDITOR,
    read_only=False,
)
def attach_resource(ctx: ToolContext, args: dict) -> str:
    return _entry_link(ctx, args, method="attach_resource", ref_key="resource", role=True)


@register_tool(
    name="detach_resource",
    description="Detach a resource from an entry. Idempotent.",
    input_schema=_link_schema("resource", "the resource by slug, name, or id"),
    min_role=ROLE_EDITOR,
    read_only=False,
)
def detach_resource(ctx: ToolContext, args: dict) -> str:
    return _entry_link(ctx, args, method="detach_resource", ref_key="resource")


# ── Tags (entry / asset / resource — one shared vocabulary) ───────────────────
# Single OR bulk: name one target (`entity`), several (`entities`), or select assets/resources by
# `filter` (type/substring). One or many `tag`/`tags`. Every (target × tag) pair is linked through
# the shared link_tag chokepoint, then asset/resource smart-collection membership is re-materialized
# (entries sync reactively; assets/resources have no reactive listener, so we resync here — the same
# thing the HTTP tags endpoint does — otherwise a freshly-tagged asset never joins its collection).
_BULK_CAP = 1000
_TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "entity_type": {"type": "string", "enum": ["entry", "asset", "resource"], "description": "what to tag (default 'entry')"},
        "entity": {"type": "string", "description": "a single entry/asset/resource by slug or id"},
        "entities": {"type": "array", "items": {"type": "string"}, "description": "several targets by slug or id (bulk)"},
        "filter": {
            "type": "object",
            "description": (
                "select targets in bulk instead of naming them (dimensions mirror smart-collection rules). Every "
                "selected target gets EVERY tag, so only filter when the same tags truly fit all of them"
            ),
            "properties": {
                "entry_types": {"type": "array", "items": {"type": "string"}, "description": "entry type slugs — entries only"},
                "statuses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "entry PUBLISH statuses (inbox, draft, needs_review, approved, published, archived) — entries only",
                },
                "collection": {"type": "string", "description": "entries in this collection (slug or name) — entries only"},
                "fields": {"type": "object", "description": "exact match on the entry type's own fields {field_key: value} — entries only"},
                "where": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "field comparisons [{field, op, value}], op eq|neq|in|contains|exists|missing|gt|gte|lt|lte — entries only",
                },
                "asset_types": {"type": "array", "items": {"type": "string"}, "description": "coarse bucket e.g. ['image','svg'] — assets only"},
                "mime_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "exact MIME e.g. ['image/svg+xml'] — assets only, finer than asset_types",
                },
                "resource_types": {"type": "array", "items": {"type": "string"}, "description": "resource types — resources only"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "select targets already carrying ANY of these tags (slug/name) — all types",
                },
                "query": {"type": "string", "description": "title/name/filename substring (all types)"},
            },
        },
        "tag": {"type": "string", "description": "a tag name or slug"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "several tags (each applied to every target) — only tags that fit every target, never a vocabulary or list of options",
        },
    },
}


def _resolve_targets(ctx: ToolContext, entity_type: str, args: dict) -> tuple[list, str | None]:
    """Resolve the target entity ids from `entity` / `entities` / `filter`. Returns (ids, error)."""
    import uuid as _uuid

    refs = ([args["entity"]] if args.get("entity") else []) + list(args.get("entities") or [])
    if refs:
        ids = [resolve_entity_id(ctx.session, ctx.group_id, entity_type, r) for r in refs]
        return [i for i in ids if isinstance(i, _uuid.UUID)], None

    s, gid = ctx.session, ctx.group_id
    filt = args.get("filter") or {}
    if entity_type == "entry":
        # The shared entry query (services/entries/query.py) — the same filters find_entries and
        # workflows understand: types, publish statuses, title, tags, collection, fields, where, dates.
        from marvin.services.entries.query import run as run_entry_query

        result = run_entry_query(s, gid, filt, limit=_BULK_CAP)
        return [e.id for e in result.rows], result.note
    if entity_type in ("asset", "resource"):
        # The shared asset/resource query (services/item_query.py) — what list_assets / list_resources and
        # trash_entries' `match` select by. A filter never matches the Trash.
        from marvin.services import item_query

        result = item_query.run(s, gid, entity_type, filt, limit=_BULK_CAP)
        return [r.id for r in result.rows], None  # a tag that doesn't exist here: no rows, no error
    return [], None  # entity_type is validated upstream; no target given


def _resync_collections(ctx: ToolContext, entity_type: str, ids) -> int:
    """Re-materialize asset/resource smart-collection membership after tag changes. Entries sync via
    SmartCollectionReactionListener; assets/resources have no reactive listener, so we do it here."""
    if entity_type not in ("asset", "resource") or not ids:
        return 0
    from marvin.db.models.platform import Assets, Resources
    from marvin.services.collections.smart_collections import sync_item

    model = {"asset": Assets, "resource": Resources}[entity_type]
    changed = 0
    for eid in ids:
        item = ctx.session.get(model, eid)
        if item:
            changed += sync_item(ctx.session, ctx.group_id, item, entity_type)
    if changed:
        ctx.session.commit()
    return changed


def _requested_tags(args: dict) -> list[str]:
    return [str(t).strip() for t in (([args["tag"]] if args.get("tag") else []) + list(args.get("tags") or [])) if str(t).strip()]


def _target_labels(ctx: ToolContext, entity_type: str, ids: list) -> list[str]:
    """Human names for target ids (entry title / asset or resource name), in the ids' order."""
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.resources import Resources

    model, col = {"entry": (Entries, Entries.title), "asset": (Assets, Assets.name), "resource": (Resources, Resources.name)}[entity_type]
    names = dict(ctx.session.query(model.id, col).filter(model.group_id == ctx.group_id, model.id.in_(ids)).all()) if ids else {}
    return [names.get(i) or str(i) for i in ids]


def _tag_bulk_write(ctx: ToolContext, args: dict, *, attach: bool) -> BulkWrite | None:
    """Size an attach/detach_tag call (targets × tags) without writing; None when the input is bad."""
    from marvin.services.tagging import TAGGABLE

    entity_type = str(args.get("entity_type") or "entry").lower()
    tags = _requested_tags(args)
    if entity_type not in TAGGABLE or not tags:
        return None
    ids, err = _resolve_targets(ctx, entity_type, args)
    if err or not ids:
        return None
    return BulkWrite(
        action="attach" if attach else "detach",
        item_kind="tag",
        items=tags,
        target_type=entity_type,
        target_ids=ids,
        label_targets=lambda shown: _target_labels(ctx, entity_type, shown),
    )


def _tag_link(ctx: ToolContext, args: dict, *, attach: bool) -> str:
    from marvin.services.tagging import TAGGABLE, link_tag

    entity_type = str(args.get("entity_type") or "entry").lower()
    if entity_type not in TAGGABLE:
        return json.dumps({"error": f"entity_type must be one of {list(TAGGABLE)}"})

    tags = _requested_tags(args)
    if not tags:
        return json.dumps({"error": "provide a tag (or tags[]) to apply"})

    ids, err = _resolve_targets(ctx, entity_type, args)
    if err:
        return json.dumps({"error": err})
    if not ids:
        return json.dumps({"error": f"no matching {entity_type}(s) for the given entity/entities/filter"})

    actor_id = getattr(ctx.user, "id", None)
    changed, unchanged, not_found, touched = 0, 0, 0, set()
    for eid in ids:
        for tag in tags:
            res = link_tag(ctx.session, ctx.group_id, entity_type, eid, tag, attach=attach, actor_id=actor_id)
            if res in ("attached", "detached"):
                changed += 1
                touched.add(eid)
            elif res in ("exists", "absent"):
                unchanged += 1
            else:
                not_found += 1

    resynced = _resync_collections(ctx, entity_type, touched)
    verb = "attached" if attach else "detached"
    out = {
        "entity_type": entity_type,
        "tags": tags,
        "targets": len(ids),
        verb: changed,
        "unchanged": unchanged,
        "not_found": not_found,
        "collections_resynced": resynced,
    }
    # Preserve the simple single-target shape when exactly one entity + one tag was given.
    if args.get("entity") and not args.get("entities") and not args.get("filter") and len(tags) == 1:
        out["entity"] = str(args.get("entity"))
        out["tag"] = tags[0]
        out["result"] = verb if changed else ("exists" if attach else "absent") if unchanged else "not_found"
    return json.dumps(out)


@register_tool(
    name="attach_tag",
    description=(
        "Attach a tag to entries/assets/resources (set entity_type). Find-or-creates the tag in the one "
        "shared workspace vocabulary, links it, and updates smart collections. Idempotent. SINGLE or BULK: "
        "name one target with `entity`, several with `entities`, or select in bulk with `filter` (entries by "
        "entry_types/statuses, assets by asset_types, resources by resource_types, ALL by tags/query — so you "
        "can re-tag everything already carrying a tag); apply one `tag` or many `tags`. One call tags the set. "
        "Choose tags PER TARGET from what that target actually is — never apply the tag vocabulary or a list of "
        "options wholesale, and never give one item contradictory tags. To tag images/assets by their content, "
        "run generate_tags on each asset (entity_type 'asset'; pass the existing tag names as input.vocabulary) — "
        "it looks at the image and keeps only what fits — or look with view_image first, then attach only what "
        "fits that asset. Big bulk writes (many targets × tags) ask the user first."
    ),
    input_schema=_TAG_SCHEMA,
    min_role=ROLE_EDITOR,
    read_only=False,
    bulk_write=lambda ctx, args: _tag_bulk_write(ctx, args, attach=True),
)
def attach_tag(ctx: ToolContext, args: dict) -> str:
    return _tag_link(ctx, args, attach=True)


@register_tool(
    name="detach_tag",
    description=(
        "Detach a tag from entries/assets/resources (set entity_type). Idempotent (the tag stays in the "
        "vocabulary). SINGLE or BULK: `entity`, `entities`, or `filter`; one `tag` or many `tags`. Big bulk "
        "removals (many targets × tags) ask the user first."
    ),
    input_schema=_TAG_SCHEMA,
    min_role=ROLE_EDITOR,
    read_only=False,
    bulk_write=lambda ctx, args: _tag_bulk_write(ctx, args, attach=False),
)
def detach_tag(ctx: ToolContext, args: dict) -> str:
    return _tag_link(ctx, args, attach=False)


# ── Collections ───────────────────────────────────────────────────────────────
@register_tool(
    name="add_to_collection",
    description="Add an entry to a collection. Idempotent. Identify the entry by slug/id and the collection by slug/name/id.",
    input_schema=_link_schema("collection", "the collection by slug, name, or id"),
    min_role=ROLE_EDITOR,
    read_only=False,
)
def add_to_collection(ctx: ToolContext, args: dict) -> str:
    return _entry_link(ctx, args, method="add_to_collection", ref_key="collection")


@register_tool(
    name="remove_from_collection",
    description="Remove an entry from a collection. Idempotent.",
    input_schema=_link_schema("collection", "the collection by slug, name, or id"),
    min_role=ROLE_EDITOR,
    read_only=False,
)
def remove_from_collection(ctx: ToolContext, args: dict) -> str:
    return _entry_link(ctx, args, method="remove_from_collection", ref_key="collection")


# ── Assets ────────────────────────────────────────────────────────────────────
@register_tool(
    name="attach_asset",
    description="Attach an existing asset (image/file) to an entry, optionally with a role (e.g. 'hero'). Idempotent. To bring in a NEW image from a URL or bytes, use import_asset first.",  # noqa: E501
    input_schema=_link_schema("asset", "the asset by slug or id", role=True),
    min_role=ROLE_EDITOR,
    read_only=False,
)
def attach_asset(ctx: ToolContext, args: dict) -> str:
    return _entry_link(ctx, args, method="attach_asset", ref_key="asset", role=True)


@register_tool(
    name="detach_asset",
    description="Detach an asset from an entry. Idempotent (the asset itself is not deleted).",
    input_schema=_link_schema("asset", "the asset by slug or id"),
    min_role=ROLE_EDITOR,
    read_only=False,
)
def detach_asset(ctx: ToolContext, args: dict) -> str:
    return _entry_link(ctx, args, method="detach_asset", ref_key="asset")


# ── Asset ingestion (bring a new image in) ────────────────────────────────────
_MAX_IMPORT_BYTES = 20 * 1024 * 1024  # 20 MB
_MAX_IMPORT_BATCH = 24  # ceiling on images ingested in one call


def _public_url_error(url: str) -> str | None:
    """SSRF fence: reject a fetch URL that isn't http(s) or whose host resolves to a non-public
    address (loopback / private / link-local / reserved — e.g. 127.0.0.1, 169.254.169.254, 10.x).
    Returns an error string, or None if the URL is safe to fetch. Callers must also disable redirect
    following so a public host can't 302 into an internal one."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(str(url))
    if parsed.scheme not in ("http", "https"):
        return "url must be http(s)"
    host = parsed.hostname
    if not host:
        return "url has no host"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        return f"could not resolve host: {e}"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return "url resolves to a non-public address — blocked"
    return None


def _recipe_roles_for_entry(ctx: ToolContext, entry_id) -> list:
    """The entry type's declared asset roles (e.g. [hero, gallery]) for role-by-position attach."""
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe

    entry = ctx.session.get(Entries, entry_id) if entry_id else None
    if not entry:
        return []
    et = ctx.session.get(EntryTypes, entry.entry_type_id)
    recipe = EntryTypeRecipe.model_validate((et.recipe_json if et else {}) or {})
    return [r.role for r in recipe.assets.roles] if (recipe.assets and recipe.assets.roles) else []


def _ingest_one_image(ctx: ToolContext, spec: dict):
    """Fetch/decode a single image spec ({url|data, filename?, name?, alt_text?}) and store it as an
    asset. Returns (asset, None) on success or (None, error_string). Applies the SSRF fence + size cap."""
    import base64
    import io
    import os
    import uuid as _uuid

    url, data = spec.get("url"), spec.get("data")
    if url:
        ssrf = _public_url_error(url)
        if ssrf:
            return None, ssrf
        try:
            import httpx

            # follow_redirects=False so a public host can't 302 the request into an internal address
            # (the SSRF fence only validated the initial host). A redirect is reported, not chased.
            resp = httpx.get(str(url), timeout=15.0, follow_redirects=False)
            if resp.is_redirect:
                return None, "url redirects — provide the direct image URL"
            resp.raise_for_status()
            raw = resp.content
        except Exception as e:  # noqa: BLE001
            return None, f"could not fetch url: {e}"
        filename = os.path.basename(str(url).split("?")[0]) or "imported"
    elif data:
        try:
            raw = base64.b64decode(str(data), validate=True)
        except Exception as e:  # noqa: BLE001
            return None, f"invalid base64 data: {e}"
        filename = spec.get("filename") or "imported.png"
    else:
        return None, "provide either 'url' or 'data' (base64)"

    if not raw:
        return None, "no image bytes"
    if len(raw) > _MAX_IMPORT_BYTES:
        return None, f"image too large ({len(raw)} bytes; max {_MAX_IMPORT_BYTES})"

    from slugify import slugify

    from marvin.repos.all_repositories import get_repositories
    from marvin.schemas.platform.assets import AssetUploadRequest
    from marvin.services.assets.asset_storage_service import AssetStorageService
    from marvin.services.storage.provider_factory import get_storage_provider

    name = (spec.get("name") or os.path.splitext(filename)[0] or "imported").strip()
    slug = f"{slugify(name) or 'asset'}-{_uuid.uuid4().hex[:6]}"  # suffix guarantees uniqueness
    upload_file = SimpleNamespace(filename=filename, file=io.BytesIO(raw))
    repos = get_repositories(ctx.session, group_id=ctx.group_id)
    try:
        asset = AssetStorageService(repos, get_storage_provider()).upload_asset(
            upload_file=upload_file,
            upload_request=AssetUploadRequest(slug=slug, name=name, alt_text=spec.get("alt_text")),
            group_id=ctx.group_id,
            user_id=ctx.user.id,
        )
    except Exception as e:  # noqa: BLE001
        return None, f"could not import asset: {e}"
    return asset, None


def _import_bulk_write(ctx: ToolContext, args: dict) -> BulkWrite | None:
    """Size an import_asset call that attaches its images to an entry: one link per image."""
    import uuid as _uuid

    specs = args.get("images")
    if not (args.get("attach_to") and isinstance(specs, list) and specs):
        return None  # a single image, or no attach — never bulk
    entry_id = resolve_entity_id(ctx.session, ctx.group_id, "entry", args["attach_to"])
    if not isinstance(entry_id, _uuid.UUID):
        return None
    names = [str((s or {}).get("name") or (s or {}).get("filename") or (s or {}).get("url") or f"image {i + 1}") for i, s in enumerate(specs)]
    return BulkWrite(
        action="attach",
        item_kind="image",
        items=names,
        target_type="entry",
        target_ids=[entry_id],
        label_targets=lambda shown: _target_labels(ctx, "entry", shown),
    )


@register_tool(
    name="import_asset",
    description=(
        "Bring NEW image(s) into the workspace as assets — from web URLs or base64 bytes (e.g. phone "
        "captures) — and optionally attach them to an entry in one call. Pass a single image via "
        "'url'/'data', or MANY at once via 'images'. When 'attach_to' is set, the images fill that "
        "entry type's recipe roles in order (first → hero, the rest → gallery), so you can populate an "
        "entry with all the photos its recipe calls for in a single call. Returns the new asset id(s) "
        "+ urls. Use attach_asset instead when the asset already exists."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "single import: an http(s) URL of the image to fetch"},
            "data": {"type": "string", "description": "single import: base64-encoded image bytes (alternative to url)"},
            "filename": {"type": "string", "description": "filename for base64 data (e.g. 'photo.jpg')"},
            "name": {"type": "string", "description": "display name (defaults to the filename)"},
            "alt_text": {"type": "string", "description": "accessibility alt text"},
            "images": {
                "type": "array",
                "description": "bulk import: several images at once. When attach_to is set they fill the entry's recipe roles in order (first → hero).",  # noqa: E501
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "data": {"type": "string"},
                        "filename": {"type": "string"},
                        "name": {"type": "string"},
                        "alt_text": {"type": "string"},
                    },
                },
            },
            "attach_to": {"type": "string", "description": "optional entry (slug/id) to attach the new asset(s) to"},
            "role": {
                "type": "string",
                "description": "single import only: override the attachment role (e.g. 'hero'); ignored for bulk, which uses recipe roles by position",  # noqa: E501
            },
        },
    },
    min_role=ROLE_EDITOR,
    read_only=False,
    bulk_write=_import_bulk_write,
)
def import_asset(ctx: ToolContext, args: dict) -> str:
    if getattr(ctx.user, "id", None) is None:
        return json.dumps({"error": "import_asset requires an authenticated user"})

    # Normalize to a list of image specs. A single url/data is the one-item (back-compat) case.
    specs = args.get("images")
    single = not (isinstance(specs, list) and specs)
    if single:
        if not (args.get("url") or args.get("data")):
            return json.dumps({"error": "provide 'url' or 'data', or an 'images' array"})
        specs = [{k: args.get(k) for k in ("url", "data", "filename", "name", "alt_text")}]
    assert isinstance(specs, list)  # both branches above leave specs a list
    if len(specs) > _MAX_IMPORT_BATCH:
        return json.dumps({"error": f"too many images ({len(specs)}; max {_MAX_IMPORT_BATCH} per call)"})

    # 1) Ingest each image, preserving order.
    results: list[dict] = []  # per-image record (asset fields, or an error)
    assets: list = []  # successfully created assets, in order
    for i, spec in enumerate(specs):
        asset, err = _ingest_one_image(ctx, spec if isinstance(spec, dict) else {})
        if err:
            results.append({"index": i, "error": err})
            continue
        assets.append(asset)
        results.append(
            {
                "index": i,
                "asset_id": str(asset.id),
                "slug": asset.slug,
                "name": asset.name,
                "url": getattr(asset, "public_url", None) or getattr(asset, "url", None),
                "assetType": getattr(asset, "asset_type", None),
            }
        )

    if not assets:  # nothing imported — surface the (first) reason as a top-level error
        return json.dumps({"error": results[0]["error"] if results else "no images provided"})

    # 2) Optionally attach to an entry, assigning recipe roles by position (first → hero, then declared).
    attached: list[dict] = []
    if args.get("attach_to"):
        entry_id = resolve_entity_id(ctx.session, ctx.group_id, "entry", args["attach_to"])
        roles = _recipe_roles_for_entry(ctx, entry_id)
        svc = _service(ctx)
        for j, asset in enumerate(assets):
            if single and args.get("role"):  # back-compat: explicit single-image role wins
                role = args["role"]
            elif roles:
                role = roles[j] if j < len(roles) else roles[-1]  # overflow reuses the last role
            else:
                role = None
            status_ = svc.attach_asset(entry_id, asset.id, role=role)
            attached.append({"asset_id": str(asset.id), "role": role, "status": status_})

    # 3) Response. Keep the single-import top-level keys for back-compat; always include the batch arrays.
    first = results[0] if not results[0].get("error") else next(r for r in results if not r.get("error"))
    out = {
        "asset_id": first["asset_id"],
        "slug": first["slug"],
        "name": first["name"],
        "url": first["url"],
        "assetType": first["assetType"],
        "imported": len(assets),
        "assets": results,
    }
    if args.get("attach_to"):
        out["attached_to"] = str(args["attach_to"])
        out["attached"] = attached
        if single:
            out["attach"] = attached[0]["status"] if attached else None
    return json.dumps(out)
