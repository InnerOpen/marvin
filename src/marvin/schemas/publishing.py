"""
Publishing API schemas.

These schemas are used for the public-facing publishing API and exclude
all admin fields, internal metadata, and unpublished content.
"""

from datetime import datetime

from pydantic import UUID4, ConfigDict, Field, field_validator

from marvin.schemas._marvin import _MarvinModel


class PublishedAssetRead(_MarvinModel):
    """
    Schema for published assets in the publishing API.

    Provides asset metadata for external sites to build proper media tags.
    Read-only, does not expose internal fields like storage_key or uploaded_by.
    """

    slug: str
    """URL-friendly identifier for the asset."""

    name: str
    """Asset name/title."""

    mime_type: str
    """MIME type of the file (e.g., 'image/jpeg', 'application/pdf')."""

    asset_type: str
    """Asset type classification (image, document, video, audio, archive, svg, other)."""

    file_size: int
    """File size in bytes."""

    width: int | None = None
    """Width in pixels (for images)."""

    height: int | None = None
    """Height in pixels (for images)."""

    alt_text: str | None = None
    """Alt text for accessibility."""

    description: str | None = None
    """Optional description of the asset."""

    public_url: str
    """Public URL to access the asset file."""

    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    """Custom metadata as JSON object."""

    tags: list[str] = []
    """Tag slugs applied to this asset."""

    model_config = ConfigDict(from_attributes=True)


class PublishedEntryAsset(_MarvinModel):
    """An asset as used by a specific entry — relationship context + asset data."""

    role: str | None = None
    position: int = 0
    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    asset: PublishedAssetRead

    model_config = ConfigDict(from_attributes=True)


class PublishedEntryTypeInfo(_MarvinModel):
    """Flattened entry type rendering and capabilities info for published entries."""

    slug: str
    renderer: str | None = None
    package: str | None = None
    version: str | None = None
    config: dict | None = None
    publishable: bool = True
    submittable: bool = False
    routable: bool = True

    model_config = ConfigDict(from_attributes=True)


class EntryTypeRendering(_MarvinModel):
    """Rendering configuration for a published entry type."""

    renderer: str | None = None
    package: str | None = None
    version: str | None = None
    config: dict | None = None


class EntryTypeCapabilities(_MarvinModel):
    """Capabilities for a published entry type."""

    publishable: bool = True
    submittable: bool = False
    routable: bool = True


class PublishedEntryTypeRead(_MarvinModel):
    """Schema for entry types in the publishing API."""

    slug: str
    name: str
    is_rendered: bool = False
    rendering: EntryTypeRendering | None = None
    capabilities: EntryTypeCapabilities | None = None

    model_config = ConfigDict(from_attributes=True)


class PublishedEntryRead(_MarvinModel):
    """
    Schema for published entries in the publishing API.

    Only includes public-facing fields. Excludes all admin metadata,
    internal fields, and user information.

    BREAKING CHANGE: content_markdown removed, replaced with data.
    Entry content is now schema-driven based on entry_type.schema_json.
    """

    slug: str
    """URL-friendly identifier for the entry."""

    title: str
    """Entry title."""

    entry_type: str
    """Entry type slug (e.g., 'page', 'article', 'project')."""

    entry_type_info: PublishedEntryTypeInfo | None = Field(default=None, serialization_alias="entryTypeInfo")
    """Rendering and capabilities info for this entry's type."""

    summary: str | None = None
    """Short blurb for compact placements (cards, related-reference lists)."""

    description: str | None = None
    """Longer descriptive lede shown under the title on the entry's own page."""

    data: dict = Field(default_factory=dict)
    """Entry content structured according to entry type schema."""

    @field_validator("data", mode="before")
    @classmethod
    def _data_never_null(cls, value: object) -> dict:
        """An entry with no custom data stores ``data_json`` as SQL NULL; the API contract is that
        ``data`` is always an object. Normalize NULL (and any non-dict) to ``{}`` so a data-less
        entry serializes cleanly instead of failing response validation with a 500."""
        return value if isinstance(value, dict) else {}

    published_at: datetime | None = None
    """Timestamp when the entry was published."""

    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    """Custom non-schema metadata as JSON object."""

    collections: list["PublishedEntryCollection"] = []
    """Collections this entry belongs to, with relationship context."""

    resources: list["PublishedEntryResource"] = []
    """Resources referenced by this entry with relationship context."""

    assets: list[PublishedEntryAsset] = []
    """Assets included in this entry with relationship context."""

    tags: list[str] = []
    """Tag slugs applied to this entry."""

    order: int | None = None
    """Sort order within a collection. Only populated when querying entries for a specific collection."""

    model_config = ConfigDict(from_attributes=True)


class PublishedEntryListItem(_MarvinModel):
    """
    Entry schema for list responses.

    Used when listing multiple entries. Carries the entry's schema fields (``data``) alongside
    the summary, memberships, tags and a resolved featured asset, but not the full asset,
    resource and collection detail of ``PublishedEntryRead``.
    """

    slug: str
    """URL-friendly identifier for the entry."""

    title: str
    """Entry title."""

    entry_type: str
    """Entry type slug (e.g., 'page', 'article', 'project')."""

    entry_type_info: PublishedEntryTypeInfo | None = Field(default=None, serialization_alias="entryTypeInfo")
    """Rendering and capabilities info for this entry's type."""

    summary: str | None = None
    """Optional short description/summary."""

    description: str | None = None
    """Longer descriptive lede shown under the title on the entry's own page."""

    data: dict = Field(default_factory=dict)
    """Entry content structured according to the entry type schema.

    Carried on list items so a site can render a whole collection from one request instead of
    re-fetching every entry for its fields (an N+1 that times out on large collections)."""

    @field_validator("data", mode="before")
    @classmethod
    def _data_never_null(cls, value: object) -> dict:
        """Same contract as ``PublishedEntryRead.data``: SQL NULL (or any non-dict) becomes ``{}``."""
        return value if isinstance(value, dict) else {}

    published_at: datetime | None = None
    """Timestamp when the entry was published."""

    status: str
    """Entry status (e.g., 'published', 'draft', 'needs_review')."""

    collections: list["PublishedEntryCollection"] = []
    """Collections this entry belongs to, with relationship context."""

    assets: list[str] = Field(default=[], serialization_alias="assetSlugs")
    """List of asset slugs included in this entry."""

    resources: list[str] = Field(default=[], serialization_alias="resourceSlugs")
    """List of resource slugs referenced by this entry."""

    tags: list[str] = []
    """Tag slugs applied to this entry."""

    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    """Custom non-schema metadata as JSON object."""

    featured_asset: PublishedAssetRead | None = Field(default=None, serialization_alias="featuredAsset")
    """First hero/featured asset, or first asset by position."""

    order: int | None = None
    """Sort order within a collection. Only populated when querying entries for a specific collection."""

    model_config = ConfigDict(from_attributes=True)


class PaginationMeta(_MarvinModel):
    """Pagination metadata."""

    total: int
    """Total number of items available."""

    page: int
    """Current page number (1-indexed)."""

    limit: int
    """Number of items per page."""

    offset: int
    """Offset for pagination."""


class PublishedEntriesResponse(_MarvinModel):
    """
    Paginated response for listing published entries.
    """

    data: list[PublishedEntryListItem]
    """List of published entries."""

    meta: PaginationMeta
    """Pagination metadata (total, page, limit)."""

    model_config = ConfigDict(from_attributes=True)


class PublishedCollectionRead(_MarvinModel):
    """
    Schema for published collections in the publishing API.

    Includes collection metadata and its published entries.
    """

    slug: str
    """URL-friendly identifier for the collection."""

    name: str
    """Collection display name."""

    description: str | None = None
    """Optional collection description."""

    is_smart: bool = False
    """Whether this is a smart collection with automatic rules."""

    smart_rules: dict | None = None
    """Smart collection rules (JSON object)."""

    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    """Custom metadata as JSON object."""

    entry_count: int
    """Number of published entries in this collection."""

    entries: list[PublishedEntryListItem]
    """Published entries in this collection."""

    model_config = ConfigDict(from_attributes=True)


class PublishedCollectionSummary(_MarvinModel):
    """
    Summary schema for published collections (for listing).

    Minimal collection info for entry contexts - only includes
    essential fields for display and ordering.
    """

    slug: str
    """URL-friendly identifier for the collection."""

    name: str
    """Collection display name."""

    description: str | None = None
    """Optional collection description."""

    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    """Custom metadata as JSON object."""

    sort_order: int
    """Display order for UI."""

    model_config = ConfigDict(from_attributes=True)


class PublishedEntryCollection(_MarvinModel):
    """A collection as used by a specific entry — relationship context + collection data."""

    role: str | None = None
    position: int = 0
    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    collection: PublishedCollectionSummary

    model_config = ConfigDict(from_attributes=True)


class PublishedResourceSummary(_MarvinModel):
    """
    Schema for published resources in standalone context.

    Provides resource metadata without entry-specific placement info.
    Used for listing resources and getting individual resource details.
    """

    slug: str
    """URL-friendly identifier for the resource."""

    name: str
    """Resource name."""

    resource_type: str
    """Type of resource (fabric, tool, supplier, etc)."""

    description: str | None = None
    """Optional description."""

    url: str | None = None
    """External URL (supplier site, GitHub repo, etc)."""

    external_id: str | None = None
    """External identifier (SKU, ISBN, etc)."""

    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    """Custom metadata as JSON object."""

    entries: list[str] = []
    """List of entry slugs that reference this resource."""

    tags: list[str] = []
    """Tag slugs applied to this resource."""

    model_config = ConfigDict(from_attributes=True)


class PublishedEntryResource(_MarvinModel):
    """A resource as used by a specific entry — relationship context + resource data."""

    role: str | None = None
    position: int = 0
    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    resource: PublishedResourceSummary

    model_config = ConfigDict(from_attributes=True)


class WorkspaceInfo(_MarvinModel):
    """
    Public workspace information for publishing API.
    """

    slug: str
    """Workspace slug."""

    name: str
    """Workspace name."""

    model_config = ConfigDict(from_attributes=True)


class SiteSeoVerification(_MarvinModel):
    """Search-engine ownership verification tokens, each rendered as a <meta name="..."> tag."""

    google: str | None = None  # google-site-verification (Google Search Console)
    bing: str | None = None  # msvalidate.01 (Bing Webmaster Tools)
    pinterest: str | None = None  # p:domain_verify (Pinterest)
    yandex: str | None = None  # yandex-verification (Yandex Webmaster)


class SiteSeo(_MarvinModel):
    """
    Structured SEO / social-sharing metadata for a workspace's published site.

    Stored under ``group_preferences.site_metadata_json['seo']`` and surfaced here, typed,
    as ``site.seo`` on the publishing API. Every field is optional — a consuming site is
    expected to fall back to the matching identity value (title, description, canonical_url)
    when a field is absent. Marvin stores and serves these values; the rendering layer emits
    the actual ``<meta>``/Open Graph/Twitter tags.
    """

    # Search / core meta
    title: str | None = None
    """Meta title override. Falls back to the site title."""
    title_template: str | None = None
    """Per-page title pattern, e.g. ``"%s | Brand"`` (``%s`` = the page title)."""
    description: str | None = None
    """Meta description. Falls back to the site description."""
    keywords: list[str] = Field(default_factory=list)
    """Keyword list (low ranking value, but some frameworks still emit them)."""
    robots: str = "index,follow"
    """robots meta directive, e.g. ``index,follow`` or ``noindex,nofollow``."""

    # Social sharing (Open Graph + Twitter/X)
    image: str | None = None
    """Default share image URL (Open Graph + Twitter). Recommended 1200×630."""
    image_alt: str | None = None
    """Alt text for the share image (og:image:alt)."""
    og_type: str = "website"
    """Open Graph type: website, article, profile, book."""
    site_name: str | None = None
    """og:site_name — the brand name, distinct from the page title."""
    twitter_card: str = "summary_large_image"
    """Twitter card style: summary_large_image or summary."""
    twitter_handle: str | None = None
    """twitter:site — the site's @handle."""
    twitter_creator: str | None = None
    """twitter:creator — the content author's @handle."""
    fb_app_id: str | None = None
    """fb:app_id — Facebook app id for domain insights."""

    # Branding / structured data
    theme_color: str | None = None
    """<meta name="theme-color"> — browser chrome / PWA color (e.g. #4f9c84)."""
    publisher: str | None = None
    """Publisher / organization name for structured data (JSON-LD, article:publisher)."""

    verification: SiteSeoVerification = Field(default_factory=SiteSeoVerification)
    """Search-engine ownership verification tokens."""


class SiteConfiguration(_MarvinModel):
    """
    Site configuration for publishing API.

    Provides the public identity and settings for a workspace's published site.
    This replaces hardcoded site.ts files in Astro projects.
    """

    title: str | None = None
    """The public title of the site."""

    tagline: str | None = None
    """A short tagline or slogan."""

    description: str | None = None
    """Site description."""

    canonical_url: str | None = None
    """The canonical URL where this site is published."""

    logo: str | None = None
    """Asset slug for the site logo. Resolve via the assets API."""

    favicon: str | None = None
    """Asset slug for the site favicon. Resolve via the assets API."""

    locale: str = "en-US"
    """Site locale (e.g., en-US, en-GB)."""

    timezone: str = "America/New_York"
    """Site timezone (e.g., America/New_York)."""

    contact_email: str | None = None
    """Primary contact email."""

    social: dict | None = None
    """Social media links (e.g., {instagram: 'url', facebook: 'url'})."""

    seo: SiteSeo | None = None
    """Structured SEO / social-sharing metadata (also present under ``metadata.seo``)."""

    metadata: dict | None = Field(default=None, serialization_alias="metadataJson")
    """Framework-specific or custom site metadata."""

    model_config = ConfigDict(from_attributes=True)


class WorkspaceSiteInfo(_MarvinModel):
    """
    Combined workspace and site configuration response.

    Returns everything an external site needs to initialize itself.
    """

    workspace: WorkspaceInfo
    """Workspace identification."""

    site: SiteConfiguration
    """Site configuration and identity."""

    model_config = ConfigDict(from_attributes=True)


class PublishedCollectionsResponse(_MarvinModel):
    """
    Paginated response for listing published collections.
    """

    data: list[PublishedCollectionSummary]
    """List of published collections."""

    meta: PaginationMeta
    """Pagination metadata."""

    model_config = ConfigDict(from_attributes=True)


class PublishedResourcesResponse(_MarvinModel):
    """
    Paginated response for listing published resources.
    """

    data: list[PublishedResourceSummary]
    """List of published resources."""

    meta: PaginationMeta
    """Pagination metadata."""

    model_config = ConfigDict(from_attributes=True)


class PublishedAssetsResponse(_MarvinModel):
    """
    Paginated response for listing published assets.
    """

    data: list[PublishedAssetRead]
    """List of published assets."""

    meta: PaginationMeta
    """Pagination metadata."""

    model_config = ConfigDict(from_attributes=True)


class PublishedFormRead(_MarvinModel):
    """
    Schema for published forms in the publishing API.

    Provides form definition for frontend to render the form.
    Does not expose internal fields like submissions_count.
    """

    slug: str
    """URL-friendly identifier for the form."""

    name: str
    """Form display name."""

    description: str | None = None
    """Optional description of the form."""

    form_schema: dict
    """Form field definitions."""

    metadata: dict | None = None
    """Custom metadata (if publicly exposed)."""

    model_config = ConfigDict(from_attributes=True)


class FormSubmissionResponse(_MarvinModel):
    """
    Response after form submission.

    Indicates success/failure and optionally provides redirect URL.
    """

    success: bool
    """Whether submission was successful."""

    message: str
    """User-facing message."""

    submission_id: UUID4 | None = None
    """Submission ID (if persisted)."""

    redirect_url: str | None = None
    """Optional redirect URL."""

    model_config = ConfigDict(from_attributes=True)
