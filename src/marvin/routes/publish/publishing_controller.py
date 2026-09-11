"""
Publishing API controller.

Provides read-only access to published content for external sites (Astro, etc.).
All routes require API client token authentication (marvin_sk_ prefix).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload, selectinload

from marvin.core.config import get_app_settings
from marvin.core.dependencies import get_publishing_context
from marvin.core.permissions import Permissions
from marvin.db.db_setup import generate_session
from marvin.db.models.platform import (
    Assets,
    Collections,
    Entries,
    EntryAssets,
    EntryCollections,
    EntryResources,
    Resources,
)
from marvin.repos.all_repositories import get_repositories
from marvin.schemas.platform.entry_type_rendering import CapabilitiesDefinition, RenderingDefinition
from marvin.schemas.publishing import (
    EntryTypeCapabilities,
    EntryTypeRendering,
    PaginationMeta,
    PublishedAssetRead,
    PublishedAssetsResponse,
    PublishedCollectionRead,
    PublishedCollectionsResponse,
    PublishedCollectionSummary,
    PublishedEntriesResponse,
    PublishedEntryAsset,
    PublishedEntryCollection,
    PublishedEntryListItem,
    PublishedEntryRead,
    PublishedEntryResource,
    PublishedEntryTypeInfo,
    PublishedEntryTypeRead,
    PublishedResourcesResponse,
    PublishedResourceSummary,
    SiteConfiguration,
    SiteSeo,
    WorkspaceInfo,
    WorkspaceSiteInfo,
)
from marvin.services.storage.provider_factory import get_storage_provider

settings = get_app_settings()

router = APIRouter()


def _entry_eager_options():
    """Common eager loading options for entry relationships."""
    return [
        selectinload(Entries.entry_collections).joinedload(EntryCollections.collection),
        selectinload(Entries.entry_assets).joinedload(EntryAssets.asset),
        selectinload(Entries.entry_resources).joinedload(EntryResources.resource),
        selectinload(Entries.tags),
    ]


def _entry_eager_options_with_type():
    """Eager loading options for entries including entry_type (prevents N+1 on type access)."""
    return _entry_eager_options() + [joinedload(Entries.entry_type)]


def _asset_eager_options():
    """Common eager loading options for asset relationships."""
    return [selectinload(Assets.entry_assets).joinedload(EntryAssets.entry), selectinload(Assets.tags)]


def _resource_eager_options():
    """Common eager loading options for resource relationships."""
    return [selectinload(Resources.entry_resources).joinedload(EntryResources.entry), selectinload(Resources.tags)]


def _build_entry_type_info(entry: Entries) -> PublishedEntryTypeInfo | None:
    """Build PublishedEntryTypeInfo from an entry's type, or None if no type."""
    if not entry.entry_type:
        return None
    rendering = RenderingDefinition(**(entry.entry_type.rendering_json or {}))
    capabilities = CapabilitiesDefinition(**(entry.entry_type.capabilities_json or {}))
    return PublishedEntryTypeInfo(
        slug=entry.entry_type.slug,
        renderer=rendering.renderer,
        package=rendering.package,
        version=rendering.version,
        config=rendering.config,
        publishable=capabilities.publishable,
        submittable=capabilities.submittable,
        routable=capabilities.routable,
    )


def _is_suggested(ea: EntryAssets) -> bool:
    """A pending AI-suggested asset link — flagged in the junction metadata, awaiting workspace
    review. These must never reach published output, so every asset serializer filters them out."""
    return bool((ea.metadata_json or {}).get("suggested"))


def _build_published_asset(ea: EntryAssets, workspace_slug: str) -> PublishedAssetRead:
    """Build a PublishedAssetRead from an entry-asset junction row."""
    return PublishedAssetRead(
        slug=ea.asset.slug,
        name=ea.asset.name,
        mime_type=ea.asset.mime_type,
        asset_type=ea.asset.asset_type,
        file_size=ea.asset.file_size,
        width=ea.asset.width,
        height=ea.asset.height,
        alt_text=ea.asset.alt_text,
        description=ea.asset.description,
        public_url=get_storage_provider().get_public_url(ea.asset.storage_key),
        metadata=ea.asset.metadata_json,
        tags=list(ea.asset.tag_names),
    )


def _resolve_featured_asset(entry: Entries, workspace_slug: str) -> PublishedAssetRead | None:
    """Resolve the featured asset for a list item: first hero/featured, then first by position."""
    sorted_assets = sorted(
        (ea for ea in entry.entry_assets if ea.asset and not _is_suggested(ea)),
        key=lambda x: x.position,
    )
    for ea in sorted_assets:
        if ea.role in ("hero", "featured"):
            return _build_published_asset(ea, workspace_slug)
    if sorted_assets:
        return _build_published_asset(sorted_assets[0], workspace_slug)
    return None


def _entry_to_list_item(entry: Entries, workspace_slug: str, include_order: bool = False) -> PublishedEntryListItem:
    """
    Convert an entry model to a PublishedEntryListItem with relationships.

    Args:
        entry: The entry model instance
        workspace_slug: Workspace slug for building asset URLs
        include_order: Whether to include sort order from junction table

    Returns:
        PublishedEntryListItem with populated relationships
    """
    collections = [
        PublishedEntryCollection(
            role=ec.role,
            position=ec.sort_order,
            metadata=ec.metadata_json,
            collection=PublishedCollectionSummary(
                slug=ec.collection.slug,
                name=ec.collection.name,
                description=ec.collection.description,
                metadata=ec.collection.metadata_json,
                sort_order=ec.collection.sort_order,
            ),
        )
        for ec in entry.entry_collections
        if ec.collection and ec.collection.is_public
    ]
    asset_slugs = [ea.asset.slug for ea in entry.entry_assets if ea.asset and not _is_suggested(ea)]
    resource_slugs = [er.resource.slug for er in entry.entry_resources if er.resource]

    item_data = {
        "slug": entry.slug,
        "title": entry.title,
        "entry_type": entry.entry_type.slug if entry.entry_type else settings.PUBLISHING_UNKNOWN_ENTRY_TYPE,
        "entry_type_info": _build_entry_type_info(entry),
        "summary": entry.summary,
        "description": entry.description,
        "data": entry.data_json,
        "published_at": entry.published_at,
        "collections": collections,
        "assets": asset_slugs,
        "resources": resource_slugs,
        "tags": list(entry.tag_names),
        "metadata": entry.metadata_json,
        "featured_asset": _resolve_featured_asset(entry, workspace_slug),
    }

    if hasattr(entry, "status") and entry.status:
        item_data["status"] = entry.status

    return PublishedEntryListItem(**item_data)


@router.get("/{workspace_slug}", response_model=WorkspaceInfo, summary="Get Workspace Info")
async def get_workspace_info(
    context: tuple = Depends(get_publishing_context),
) -> WorkspaceInfo:
    """
    Get public workspace information.

    Returns basic workspace metadata for site consumption.

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:published_entries (minimal permission to access publishing API)
    """
    api_client, group, perms = context

    # Require at least one publishing permission to access workspace info
    perms.require_any_permission([Permissions.READ_PUBLISHED_ENTRIES, Permissions.READ_ALL_ENTRIES], "workspace information")

    return WorkspaceInfo(
        slug=group.slug,
        name=group.name,
    )


@router.get("/{workspace_slug}/site", response_model=WorkspaceSiteInfo, summary="Get Site Configuration")
async def get_site_configuration(
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
) -> WorkspaceSiteInfo:
    """
    Get workspace and site configuration.

    Returns complete site identity and settings for external sites (Astro, etc.).
    This replaces hardcoded site.ts files - all site configuration lives in Marvin.

    **Response includes:**
    - Workspace identity (name, slug)
    - Site settings (title, tagline, description, URLs)
    - Contact information
    - Social media links
    - Localization settings
    - Custom metadata

    **Use case**: Astro site initialization, meta tags, social links, contact forms.

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:published_entries (minimal permission to access publishing API)
    """
    api_client, group, perms = context

    # Require at least one publishing permission to access site configuration
    perms.require_any_permission([Permissions.READ_PUBLISHED_ENTRIES, Permissions.READ_ALL_ENTRIES], "site configuration")

    # Get group preferences (includes site configuration)
    from marvin.db.models.groups import GroupPreferencesModel

    prefs = session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == group.id).first()

    # Parse the structured SEO block (stored under metadata.seo) into its typed model, so
    # consumers get a validated site.seo alongside the raw metadata blob.
    site_metadata = prefs.site_metadata_json if prefs else None
    seo_raw = (site_metadata or {}).get("seo")
    seo = SiteSeo(**seo_raw) if isinstance(seo_raw, dict) and seo_raw else None

    # Build site configuration from preferences (with sensible defaults)
    site_config = SiteConfiguration(
        title=prefs.site_title if prefs and prefs.site_title else group.name,
        tagline=prefs.site_tagline if prefs else None,
        description=prefs.site_description if prefs else None,
        canonical_url=prefs.site_canonical_url if prefs else None,
        logo=prefs.site_logo if prefs else None,
        favicon=prefs.site_favicon if prefs else None,
        locale=prefs.site_locale if prefs and prefs.site_locale else "en-US",
        timezone=prefs.site_timezone if prefs and prefs.site_timezone else "America/New_York",
        contact_email=prefs.site_contact_email if prefs else None,
        social=prefs.site_social_json if prefs else None,
        seo=seo,
        metadata=site_metadata,
    )

    return WorkspaceSiteInfo(
        workspace=WorkspaceInfo(
            slug=group.slug,
            name=group.name,
        ),
        site=site_config,
    )


@router.get(
    "/{workspace_slug}/entry-types",
    response_model=list[PublishedEntryTypeRead],
    summary="List Entry Types",
)
async def list_entry_types(
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
) -> list[PublishedEntryTypeRead]:
    """
    List all entry types in the workspace with rendering and capabilities info.

    Returns a lean response with only renderer-relevant fields, suitable for
    build-time validation of renderer registries.

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:published_entries OR read:all_entries
    """
    api_client, group, perms = context

    perms.require_any_permission([Permissions.READ_PUBLISHED_ENTRIES, Permissions.READ_ALL_ENTRIES], "entry types")

    from sqlalchemy import or_

    from marvin.db.models.platform import EntryTypes

    entry_types = (
        session.query(EntryTypes)
        .filter(or_(EntryTypes.group_id == group.id, EntryTypes.group_id.is_(None)))
        .order_by(EntryTypes.sort_order, EntryTypes.name)
        .all()
    )

    result = []
    for et in entry_types:
        rendering_dict = et.rendering_json or {}
        capabilities_dict = et.capabilities_json or {}

        rendering = EntryTypeRendering(**rendering_dict) if rendering_dict else None
        capabilities = EntryTypeCapabilities(**capabilities_dict) if capabilities_dict else EntryTypeCapabilities()

        result.append(
            PublishedEntryTypeRead(
                slug=et.slug,
                name=et.name,
                is_rendered=et.is_rendered,
                rendering=rendering,
                capabilities=capabilities,
            )
        )

    return result


@router.get(
    "/{workspace_slug}/entries",
    response_model=PublishedEntriesResponse,
    summary="List Published Entries",
)
async def list_published_entries(
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
    entry_type: str | None = Query(None, description="Filter by entry type slug"),
    collection: str | None = Query(None, description="Filter by collection slug"),
    tag: str | None = Query(None, description="Filter by tag slug(s), comma-separated (matches ANY)"),
    slug: str | None = Query(None, description="Filter by specific slug(s), comma-separated"),
    updated_since: str | None = Query(None, description="Filter by entries updated since ISO datetime"),
    limit: int = Query(settings.PUBLISHING_DEFAULT_PAGE_SIZE, ge=1, le=settings.PUBLISHING_MAX_PAGE_SIZE, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> PublishedEntriesResponse:
    """
    List all published entries in the workspace.

    Supports filtering by entry type, collection, slug, and updated date, plus pagination.

    **Filters:**
    - Only returns entries with `status = 'published'`
    - Scoped to the workspace associated with the API client
    - `entry_type`: Filter by entry type slug
    - `collection`: Filter by collection slug
    - `tag`: Filter by tag slug(s), comma-separated — matches entries carrying ANY of them
    - `slug`: Filter by specific slug(s), comma-separated for batch fetching
    - `updated_since`: ISO datetime, returns entries updated after this time

    **Use cases:**
    - `?entry_type=page` - Get all static pages
    - `?collection=projects` - Get all project entries
    - `?tag=leather,waxed` - Get entries tagged leather OR waxed
    - `?slug=about,contact,sizing` - Batch fetch specific pages
    - `?updated_since=2026-07-01T00:00:00Z` - Incremental builds

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:published_entries OR read:all_entries
    """
    api_client, group, perms = context

    # Require permission to read entries
    perms.require_any_permission([Permissions.READ_PUBLISHED_ENTRIES, Permissions.READ_ALL_ENTRIES], "published entries")

    # Get repositories scoped to this workspace
    get_repositories(session, group_id=group.id)

    # Build query for published entries with eager loading to prevent N+1 queries
    query = (
        session.query(Entries)
        .filter(
            Entries.group_id == group.id,
            Entries.status == settings.PUBLISHING_DEFAULT_STATUS,
        )
        .options(*_entry_eager_options_with_type())
    )

    # Filter by entry type if specified
    if entry_type:
        from marvin.db.models.platform import EntryTypes

        entry_type_obj = session.query(EntryTypes).filter(EntryTypes.group_id == group.id, EntryTypes.slug == entry_type).first()

        if not entry_type_obj:
            # Return empty list if entry type doesn't exist
            return PublishedEntriesResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=(offset // limit) + 1,
                    limit=limit,
                    offset=offset,
                ),
            )

        query = query.filter(Entries.entry_type_id == entry_type_obj.id)

    # Filter by collection if specified
    if collection:
        from marvin.db.models.platform import EntryCollections

        # Get collection
        collection_obj = session.query(Collections).filter(Collections.group_id == group.id, Collections.slug == collection).first()

        if not collection_obj:
            # Return empty list if collection doesn't exist
            return PublishedEntriesResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=(offset // limit) + 1,
                    limit=limit,
                    offset=offset,
                ),
            )

        # Join with entry_collections to filter
        query = query.join(EntryCollections).filter(EntryCollections.collection_id == collection_obj.id)

    # Filter by tag slug(s) if specified — matches entries carrying ANY of the given tags.
    if tag:
        from slugify import slugify

        from marvin.db.models.platform import Tags

        # Slugify so a caller can pass "Waxed Canvas" or "waxed-canvas". `.any()` is an EXISTS
        # subquery — no join, so no duplicate rows and no interaction with the collection join.
        want = [slugify(t.strip()) for t in tag.split(",") if t.strip()]
        if want:
            query = query.filter(Entries.tags.any(Tags.slug.in_(want)))

    # Filter by slug(s) if specified
    if slug:
        slugs = [s.strip() for s in slug.split(",")]
        query = query.filter(Entries.slug.in_(slugs))

    # Filter by updated_since if specified
    if updated_since:
        from datetime import datetime

        try:
            updated_dt = datetime.fromisoformat(updated_since.replace("Z", "+00:00"))
            query = query.filter(Entries.update_at >= updated_dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date format for updated_since: {updated_since}. "
                "Expected ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS with optional Z or timezone offset)",
            ) from None

    # Get total count
    total = query.count()

    # Apply pagination
    entries = query.order_by(Entries.published_at.desc()).offset(offset).limit(limit).all()

    # Convert to list items
    data = [_entry_to_list_item(entry, group.slug) for entry in entries]

    return PublishedEntriesResponse(
        data=data,
        meta=PaginationMeta(
            total=total,
            page=(offset // limit) + 1,
            limit=limit,
            offset=offset,
        ),
    )


@router.get(
    "/{workspace_slug}/entries/{slug}",
    response_model=PublishedEntryRead,
    summary="Get Published Entry",
)
async def get_published_entry(
    slug: str,
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
) -> PublishedEntryRead:
    """
    Get a single published entry by slug.

    Returns full entry content including Markdown body.

    **Filters:**
    - Only returns entry if `status = 'published'`

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:published_entries OR read:all_entries

    **Raises:**
    - 404: Entry not found or not published
    """
    api_client, group, perms = context

    # Require permission to read entries
    perms.require_any_permission([Permissions.READ_PUBLISHED_ENTRIES, Permissions.READ_ALL_ENTRIES], "published entry")

    # Query published entry with eager loading to prevent N+1 queries
    entry = (
        session.query(Entries)
        .filter(
            Entries.group_id == group.id,
            Entries.slug == slug,
            Entries.status == settings.PUBLISHING_DEFAULT_STATUS,
        )
        .options(*_entry_eager_options_with_type())
        .first()
    )

    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    # Get collections with junction context + collection data
    collections = [
        PublishedEntryCollection(
            role=ec.role,
            position=ec.sort_order,
            metadata=ec.metadata_json,
            collection=PublishedCollectionSummary(
                slug=ec.collection.slug,
                name=ec.collection.name,
                description=ec.collection.description,
                is_smart=ec.collection.is_smart,
                smart_rules=ec.collection.smart_rules,
                metadata=ec.collection.metadata_json,
                entry_count=0,
                sort_order=ec.collection.sort_order,
                icon=ec.collection.icon,
                color=ec.collection.color,
            ),
        )
        for ec in entry.entry_collections
        if ec.collection and ec.collection.is_public
    ]

    # Get resources for this entry (wrapped with relationship context)
    resources = [
        PublishedEntryResource(
            role=er.role,
            position=er.position,
            metadata=er.metadata_json,
            resource=PublishedResourceSummary(
                slug=er.resource.slug,
                name=er.resource.name,
                resource_type=er.resource.resource_type,
                description=er.resource.description,
                url=er.resource.url,
                external_id=er.resource.external_id,
                metadata=er.resource.metadata_json,
                tags=list(er.resource.tag_names),
            ),
        )
        for er in entry.entry_resources
        if er.resource
    ]

    # Get assets for this entry (wrapped with relationship context)
    assets = [
        PublishedEntryAsset(
            role=ea.role,
            position=ea.position,
            metadata=ea.metadata_json,
            asset=_build_published_asset(ea, group.slug),
        )
        for ea in entry.entry_assets
        if ea.asset and not _is_suggested(ea)
    ]

    return PublishedEntryRead(
        slug=entry.slug,
        title=entry.title,
        entry_type=entry.entry_type.slug if entry.entry_type else settings.PUBLISHING_UNKNOWN_ENTRY_TYPE,
        entry_type_info=_build_entry_type_info(entry),
        summary=entry.summary,
        description=entry.description,
        data=entry.data_json,
        published_at=entry.published_at,
        metadata=entry.metadata_json,
        collections=collections,
        resources=resources,
        assets=assets,
        tags=list(entry.tag_names),
    )


@router.get(
    "/{workspace_slug}/collections",
    response_model=PublishedCollectionsResponse,
    summary="List Collections",
)
async def list_published_collections(
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
    limit: int = Query(settings.PUBLISHING_DEFAULT_PAGE_SIZE, ge=1, le=settings.PUBLISHING_MAX_PAGE_SIZE, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> PublishedCollectionsResponse:
    """
    List all collections in the workspace.

    Returns collection summaries with entry counts (published entries only).

    **Use case**: Building navigation menus, collection indexes.

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:collections
    """
    api_client, group, perms = context

    # Require permission to read collections
    perms.require_permission(Permissions.READ_COLLECTIONS, "collections")

    # Get total count (public collections only — system/internal collections are never published)
    total = (
        session.query(Collections)
        .filter(Collections.group_id == group.id, Collections.is_public == True)  # noqa: E712
        .count()
    )

    # Get paginated collections for this workspace (public only)
    collections = (
        session.query(Collections)
        .filter(Collections.group_id == group.id, Collections.is_public == True)  # noqa: E712
        .order_by(Collections.sort_order, Collections.name)
        .limit(limit)
        .offset(offset)
        .all()
    )

    # Build response with entry counts
    from sqlalchemy import func

    from marvin.db.models.platform import EntryCollections

    # Get entry counts for all collections in ONE query (prevents N+1)
    collection_ids = [c.id for c in collections]
    entry_counts_query = (
        session.query(
            EntryCollections.collection_id,
            func.count(Entries.id).label("entry_count"),
        )
        .join(Entries)
        .filter(
            EntryCollections.collection_id.in_(collection_ids),
            Entries.status == settings.PUBLISHING_DEFAULT_STATUS,
        )
        .group_by(EntryCollections.collection_id)
        .all()
    )

    # Create a map of collection_id -> entry_count for O(1) lookup
    entry_count_map = dict(entry_counts_query)

    result = []
    for collection in collections:
        # Get entry count from the preloaded map (default to 0 if no entries)
        entry_count = entry_count_map.get(collection.id, 0)

        result.append(
            PublishedCollectionSummary(
                slug=collection.slug,
                name=collection.name,
                description=collection.description,
                is_smart=collection.is_smart,
                smart_rules=collection.smart_rules,
                metadata=collection.metadata_json,
                entry_count=entry_count,
                sort_order=collection.sort_order,
                icon=collection.icon,
                color=collection.color,
            )
        )

    return PublishedCollectionsResponse(
        data=result,
        meta=PaginationMeta(
            total=total,
            page=(offset // limit) + 1,
            limit=limit,
            offset=offset,
        ),
    )


@router.get(
    "/{workspace_slug}/collections/{collection_slug}",
    response_model=PublishedCollectionRead,
    summary="Get Collection with Entries",
)
async def get_published_collection(
    collection_slug: str,
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
) -> PublishedCollectionRead:
    """
    Get a collection with its published entries.

    Returns collection metadata and all published entries in the collection.

    **Filters:**
    - Only includes entries with `status = 'published'`

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:collections

    **Raises:**
    - 404: Collection not found
    """
    api_client, group, perms = context

    # Require permission to read collections
    perms.require_permission(Permissions.READ_COLLECTIONS, "collection")

    # Get collection (public only — system/internal collections are not published)
    collection = (
        session.query(Collections)
        .filter(
            Collections.group_id == group.id,
            Collections.slug == collection_slug,
            Collections.is_public == True,  # noqa: E712
        )
        .first()
    )

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    # Get entries in this collection with eager loading to prevent N+1 queries
    # Filter by status based on permissions
    from marvin.db.models.platform import EntryCollections

    query = (
        session.query(Entries)
        .join(EntryCollections)
        .filter(EntryCollections.collection_id == collection.id)
        .options(*_entry_eager_options_with_type())
    )

    # Only filter to published entries if user doesn't have permission to read all
    if not perms.has_permission(Permissions.READ_ALL_ENTRIES):
        query = query.filter(Entries.status == settings.PUBLISHING_DEFAULT_STATUS)

    entries = query.order_by(EntryCollections.sort_order.asc(), Entries.published_at.desc()).all()

    # Convert to list items
    entry_items = []
    for entry in entries:
        item = _entry_to_list_item(entry, group.slug)
        # Add collection-specific sort order
        order = next((ec.sort_order for ec in entry.entry_collections if ec.collection_id == collection.id), None)
        if order is not None:
            item.order = order
        entry_items.append(item)

    return PublishedCollectionRead(
        slug=collection.slug,
        name=collection.name,
        description=collection.description,
        is_smart=collection.is_smart,
        smart_rules=collection.smart_rules,
        metadata=collection.metadata_json,
        entry_count=len(entry_items),
        entries=entry_items,
    )


@router.get(
    "/{workspace_slug}/assets",
    response_model=PublishedAssetsResponse,
    summary="List Assets",
)
async def list_published_assets(
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
    type: str | None = Query(None, description="Filter by MIME type prefix (image, video, audio, application)"),
    limit: int = Query(settings.PUBLISHING_DEFAULT_PAGE_SIZE, ge=1, le=settings.PUBLISHING_MAX_PAGE_SIZE, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> PublishedAssetsResponse:
    """
    List all assets in the workspace.

    Returns asset metadata for external sites to reference.

    **Filters:**
    - `type`: Filter by MIME type prefix (image, video, audio, application)
    - Scoped to the workspace associated with the API client

    **Use cases:**
    - `?type=image` - Get all images
    - `?type=video` - Get all videos
    - Build asset galleries, media libraries

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:assets
    """
    api_client, group, perms = context

    # Require permission to read assets
    perms.require_permission(Permissions.READ_ASSETS, "assets")

    # Build query for assets with eager loading to prevent N+1 queries
    query = session.query(Assets).filter(Assets.group_id == group.id).options(*_asset_eager_options())

    # Filter by MIME type prefix if specified
    if type:
        query = query.filter(Assets.mime_type.like(f"{type}/%"))

    # Get total count
    total = query.count()

    # Apply pagination
    assets = query.order_by(Assets.name).offset(offset).limit(limit).all()

    # Convert to response schema
    provider = get_storage_provider()
    data = []
    for asset in assets:
        # Get published entry slugs that use this asset
        entry_slugs = [
            ea.entry.slug for ea in asset.entry_assets if ea.entry and ea.entry.status == settings.PUBLISHING_DEFAULT_STATUS and not _is_suggested(ea)
        ]

        data.append(
            PublishedAssetRead(
                slug=asset.slug,
                name=asset.name,
                mime_type=asset.mime_type,
                asset_type=asset.asset_type,
                file_size=asset.file_size,
                width=asset.width,
                height=asset.height,
                alt_text=asset.alt_text,
                description=asset.description,
                public_url=provider.get_public_url(asset.storage_key),
                metadata=asset.metadata_json,
                entries=entry_slugs,
                tags=list(asset.tag_names),
            )
        )

    return PublishedAssetsResponse(
        data=data,
        meta=PaginationMeta(
            total=total,
            page=(offset // limit) + 1,
            limit=limit,
            offset=offset,
        ),
    )


@router.get(
    "/{workspace_slug}/assets/{asset_slug}",
    response_model=PublishedAssetRead,
    summary="Get Published Asset Metadata",
)
async def get_published_asset(
    asset_slug: str,
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
) -> PublishedAssetRead:
    """
    Get asset metadata for published content.

    Returns asset information (name, mime_type, dimensions, alt_text) for consumption
    by external sites.

    **Use case**: Astro site fetches asset metadata to build <img> tags with proper
    dimensions and alt text.

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:assets

    **Raises:**
    - 404: Asset not found

    **Note**: Actual file serving (GET /assets/{slug}/file) is deferred to Phase 7.
    """
    api_client, group, perms = context

    # Require permission to read assets
    perms.require_permission(Permissions.READ_ASSETS, "asset")

    asset = (
        session.query(Assets)
        .filter(
            Assets.group_id == group.id,
            Assets.slug == asset_slug,
        )
        .options(*_asset_eager_options())
        .first()
    )

    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    # Get published entry slugs that use this asset
    entry_slugs = [
        ea.entry.slug for ea in asset.entry_assets if ea.entry and ea.entry.status == settings.PUBLISHING_DEFAULT_STATUS and not _is_suggested(ea)
    ]

    return PublishedAssetRead(
        slug=asset.slug,
        name=asset.name,
        mime_type=asset.mime_type,
        asset_type=asset.asset_type,
        file_size=asset.file_size,
        width=asset.width,
        height=asset.height,
        alt_text=asset.alt_text,
        description=asset.description,
        public_url=get_storage_provider().get_public_url(asset.storage_key),
        metadata=asset.metadata_json,
        entries=entry_slugs,
        tags=list(asset.tag_names),
    )


@router.get(
    "/{workspace_slug}/assets/{asset_slug}/file",
    summary="Serve Asset File",
)
async def serve_asset_file(
    asset_slug: str,
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
):
    """
    Serve the actual asset file content.

    This endpoint proxies through to the storage provider to serve the asset file.
    For local storage, it redirects to the static file path.
    For S3 storage, it could generate a signed URL or proxy the content.

    **Use case**: Browsers fetching images, PDFs, videos via their public URL.

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:assets

    **Raises:**
    - 404: Asset not found
    """
    from fastapi.responses import RedirectResponse

    api_client, group, perms = context

    # Require permission to access asset files
    perms.require_permission(Permissions.READ_ASSETS, "asset file")

    asset = (
        session.query(Assets)
        .filter(
            Assets.group_id == group.id,
            Assets.slug == asset_slug,
        )
        .first()
    )

    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    return RedirectResponse(url=get_storage_provider().get_public_url(asset.storage_key))


@router.get(
    "/{workspace_slug}/resources",
    response_model=PublishedResourcesResponse,
    summary="List Resources",
)
async def list_published_resources(
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
    resource_type: str | None = Query(None, description="Filter by resource type"),
    limit: int = Query(settings.PUBLISHING_DEFAULT_PAGE_SIZE, ge=1, le=settings.PUBLISHING_MAX_PAGE_SIZE, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> PublishedResourcesResponse:
    """
    List all resources in the workspace.

    Returns resource metadata for external sites to reference.

    **Filters:**
    - `resource_type`: Filter by resource type (fabric, tool, supplier, etc.)
    - Scoped to the workspace associated with the API client

    **Use cases:**
    - `?resource_type=fabric` - Get all fabrics
    - `?resource_type=tool` - Get all tools
    - Build resource directories, material libraries

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:resources
    """
    api_client, group, perms = context

    # Require permission to read resources
    perms.require_permission(Permissions.READ_RESOURCES, "resources")

    # Build query for resources with eager loading to prevent N+1 queries
    query = session.query(Resources).filter(Resources.group_id == group.id).options(*_resource_eager_options())

    # Filter by resource type if specified
    if resource_type:
        query = query.filter(Resources.resource_type == resource_type)

    # Get total count
    total = query.count()

    # Apply pagination
    resources = query.order_by(Resources.name).offset(offset).limit(limit).all()

    # Convert to response schema
    data = []
    for resource in resources:
        # Get published entry slugs that reference this resource
        entry_slugs = [er.entry.slug for er in resource.entry_resources if er.entry and er.entry.status == settings.PUBLISHING_DEFAULT_STATUS]

        data.append(
            PublishedResourceSummary(
                slug=resource.slug,
                name=resource.name,
                resource_type=resource.resource_type,
                description=resource.description,
                url=resource.url,
                external_id=resource.external_id,
                metadata=resource.metadata_json,
                entries=entry_slugs,
                tags=list(resource.tag_names),
            )
        )

    return PublishedResourcesResponse(
        data=data,
        meta=PaginationMeta(
            total=total,
            page=(offset // limit) + 1,
            limit=limit,
            offset=offset,
        ),
    )


@router.get(
    "/{workspace_slug}/resources/{resource_slug}",
    response_model=PublishedResourceSummary,
    summary="Get Resource",
)
async def get_published_resource(
    resource_slug: str,
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
) -> PublishedResourceSummary:
    """
    Get a single resource by slug.

    Returns resource metadata for external sites to reference.

    **Use case**: Resource detail pages, material information displays.

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:resources

    **Raises:**
    - 404: Resource not found
    """
    api_client, group, perms = context

    # Require permission to read resources
    perms.require_permission(Permissions.READ_RESOURCES, "resource")

    # Query resource with eager loading to prevent N+1 queries
    resource = (
        session.query(Resources)
        .filter(
            Resources.group_id == group.id,
            Resources.slug == resource_slug,
        )
        .options(*_resource_eager_options())
        .first()
    )

    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    # Get published entry slugs that reference this resource
    entry_slugs = [er.entry.slug for er in resource.entry_resources if er.entry and er.entry.status == settings.PUBLISHING_DEFAULT_STATUS]

    return PublishedResourceSummary(
        slug=resource.slug,
        name=resource.name,
        resource_type=resource.resource_type,
        description=resource.description,
        url=resource.url,
        external_id=resource.external_id,
        metadata=resource.metadata_json,
        entries=entry_slugs,
        tags=list(resource.tag_names),
    )


@router.get(
    "/{workspace_slug}/resources/{resource_slug}/entries",
    response_model=list[PublishedEntryListItem],
    summary="Get Resource Entries",
)
async def get_resource_entries(
    resource_slug: str,
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
) -> list[PublishedEntryListItem]:
    """
    Get all published entries that reference a resource.

    Returns entries that use this resource (e.g., projects using a fabric).

    **Filters:**
    - Only returns entries with `status = 'published'`

    **Use case**: "View projects using this fabric" links on resource pages.

    **Authentication**: Requires API client token (marvin_sk_*)
    **Permissions**: read:resources

    **Raises:**
    - 404: Resource not found
    """
    api_client, group, perms = context

    # Require permission to read resources
    perms.require_permission(Permissions.READ_RESOURCES, "resource entries")

    # Get resource
    resource = (
        session.query(Resources)
        .filter(
            Resources.group_id == group.id,
            Resources.slug == resource_slug,
        )
        .first()
    )

    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    # Get published entries that reference this resource with eager loading
    from marvin.db.models.platform import EntryResources

    entries = (
        session.query(Entries)
        .join(EntryResources)
        .filter(
            EntryResources.resource_id == resource.id,
            Entries.status == settings.PUBLISHING_DEFAULT_STATUS,
        )
        .options(*_entry_eager_options_with_type())
        .order_by(Entries.published_at.desc())
        .all()
    )

    # Convert to list items using shared helper
    return [_entry_to_list_item(entry, group.slug) for entry in entries]
