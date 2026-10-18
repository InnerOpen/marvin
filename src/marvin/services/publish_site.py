"""The site block of the publishing API (``GET /api/publish/{workspace}/site``), shared with the admin's
"preview what a site receives" so both answer the same. A site gets URLs for its images, never asset slugs:
the publishing API has no asset endpoints to resolve one with. That covers ``metadata.brand`` too: each
string value there is a site image, resolved the same way."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from marvin.db.models.groups import GroupPreferencesModel, Groups
from marvin.db.models.platform import Assets
from marvin.schemas.publishing import SiteConfiguration, SitePrivacy, SiteSeo, WorkspaceInfo, WorkspaceSiteInfo
from marvin.services.media_embeds.publish import site_embeds
from marvin.services.storage.provider_factory import asset_public_url


def site_image_url(session: Session, group_id, value: str | None) -> str | None:
    """A site-settings image (logo, favicon, share image) as the URL a site loads it from.

    The setting names an asset by slug or id: it becomes the asset's public URL, or None when that asset is
    in the Trash or doesn't exist (the link stays for a restore; the site never sees it). A value that is
    already a URL passes through, unless its storage key is a trashed asset's, which gives None too."""
    value = (value or "").strip()
    if not value:
        return None
    named = [Assets.slug == value]
    try:
        named.append(Assets.id == UUID(value))
    except ValueError:
        pass
    asset = session.query(Assets).filter(Assets.group_id == group_id, Assets.scope == "library", or_(*named)).first()
    if asset is not None:
        return None if asset.trashed_at is not None else asset_public_url(asset)
    if "/" not in value and ":" not in value:
        return None  # not a URL, and no such asset
    trashed = session.query(Assets.storage_key).filter(Assets.group_id == group_id, Assets.trashed_at.isnot(None)).all()
    return None if any(key and key in value for (key,) in trashed) else value


def _site_privacy(site_metadata: dict | None) -> SitePrivacy | None:
    """The typed ``privacy`` block, or None when absent. A malformed stored block is ignored (the
    save path rejects bad input, so this only guards data written some other way)."""
    raw = (site_metadata or {}).get("privacy")
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        return SitePrivacy.model_validate(raw)
    except ValidationError:
        return None


def build_site_info(session: Session, group: Groups) -> WorkspaceSiteInfo:
    """The workspace's identity and site settings as a site receives them."""
    prefs = session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == group.id).first()

    # The structured SEO block (stored under metadata.seo) as a typed model, beside the raw metadata blob.
    site_metadata = prefs.site_metadata_json if prefs else None
    seo_raw = (site_metadata or {}).get("seo")
    seo = SiteSeo(**seo_raw) if isinstance(seo_raw, dict) and seo_raw else None
    metadata = site_metadata
    if seo is not None:
        seo.image = site_image_url(session, group.id, seo.image)
        if "image" in seo_raw:  # the raw blob carries the same block: no slug, no trashed image there either
            metadata = {**site_metadata, "seo": {**seo_raw, "image": seo.image}}
    brand = (site_metadata or {}).get("brand")
    if isinstance(brand, dict) and brand:  # brand.<name>: a site's named brand images (seal, portrait…)
        resolved = {k: site_image_url(session, group.id, v) if isinstance(v, str) else v for k, v in brand.items()}
        metadata = {**(metadata or {}), "brand": resolved}

    site_config = SiteConfiguration(
        title=prefs.site_title if prefs and prefs.site_title else group.name,
        tagline=prefs.site_tagline if prefs else None,
        description=prefs.site_description if prefs else None,
        canonical_url=prefs.site_canonical_url if prefs else None,
        logo=site_image_url(session, group.id, prefs.site_logo) if prefs else None,
        favicon=site_image_url(session, group.id, prefs.site_favicon) if prefs else None,
        locale=prefs.site_locale if prefs and prefs.site_locale else "en-US",
        timezone=prefs.site_timezone if prefs and prefs.site_timezone else "America/New_York",
        contact_email=prefs.site_contact_email if prefs else None,
        social=prefs.site_social_json if prefs else None,
        seo=seo,
        privacy=_site_privacy(site_metadata),
        embeds=site_embeds(site_metadata),
        metadata=metadata,
    )
    return WorkspaceSiteInfo(workspace=WorkspaceInfo(slug=group.slug, name=group.name), site=site_config)
