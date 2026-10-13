"""``embeds`` and ``site.embeds`` for the publishing API.

Read-only and offline: the media links come from the entry's stored fields, the details from the
``media_embed_cache`` (one query for a whole page of entries). A link with no cache row yet still
publishes — as a player when the link alone builds one, else as a link card. Publishing never calls a
provider. Stored markdown is never rewritten; a site that doesn't know ``embeds`` keeps showing links.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from marvin.schemas.publishing import PublishedEmbed, PublishedEmbedIframe, PublishedEmbedLink, SiteEmbeds

from .cache import cached
from .extract import entry_embed_urls
from .html import REFERRER_POLICY, link_card_html, player_html
from .matcher import match_url
from .providers import frame_sources

_VERB = {"video": "Watch", "playlist": "Listen", "audio": "Listen", "podcast": "Listen"}


def site_embeds(site_metadata: Any) -> SiteEmbeds:
    """The workspace's embed settings from ``site_metadata_json['embeds']`` (defaults when unset or invalid)."""
    raw = (site_metadata or {}).get("embeds") if isinstance(site_metadata, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    mode = raw.get("mode") if raw.get("mode") in ("direct", "click_to_load") else "click_to_load"
    consent = raw.get("consentText", raw.get("consent_text"))
    values: dict[str, Any] = {"mode": mode, "frame_sources": frame_sources()}
    if isinstance(consent, str) and consent.strip():
        values["consent_text"] = consent.strip()
    return SiteEmbeds(**values)


def build_embed(url: str, row: Any, settings: SiteEmbeds) -> PublishedEmbed | None:
    """One ``PublishedEmbed`` from the link (as written) and its cache row (or None). None for a link that
    isn't (or is no longer) a supported media link."""
    match = match_url(url)
    if match is None:
        return None
    provider = match.provider
    target = match.target

    if row is not None and row.provider == provider.key:
        status, kind = row.status, row.kind
        src, canonical = row.embed_src, row.canonical_url or target.canonical_url
        title, author, thumb = row.title, row.author_name, row.thumbnail_url
        height, aspect = row.height, row.aspect_ratio
    else:
        status, kind = ("ok" if target.src else "link"), target.kind
        src, canonical = target.src, target.canonical_url
        title = author = thumb = None
        height, aspect = target.height, target.aspect_ratio

    # Defence in depth: whatever the cache says, only a src on this provider's own frame hosts plays.
    if status == "ok" and not provider.frame_host_ok(src):
        status, src = "link", None
    if kind not in ("video", "audio", "podcast", "playlist"):
        kind = target.kind

    link_title = title or f"{_VERB.get(kind, 'Open')} on {provider.name}"
    link = PublishedEmbedLink(href=canonical, title=link_title, provider_name=provider.name)
    iframe = None
    if status == "ok" and src:
        iframe = PublishedEmbedIframe(
            src=src,
            title=title or f"{provider.name} player",
            allow=provider.allow_for(kind),
            sandbox=provider.sandbox,
            referrerpolicy=REFERRER_POLICY,
            aspect_ratio=None if height else (aspect or "16/9"),
            height=height,
        )
        html = player_html(
            provider=provider.key,
            provider_name=provider.name,
            kind=kind,
            iframe=iframe.model_dump(by_alias=True),
            frame_hosts=list(provider.frame_hosts),
            link_href=canonical,
            link_title=link_title,
            title=title,
            mode=settings.mode,
            consent_text=settings.consent_text,
        )
    else:
        html = link_card_html(provider=provider.key, href=canonical, title=link_title, provider_name=provider.name, has_title=bool(title))

    return PublishedEmbed(
        url=match.url,
        canonical_url=canonical,
        provider=provider.key,
        provider_name=provider.name,
        kind=kind,
        status=status if status in ("ok", "link", "unavailable") else "link",
        title=title,
        author_name=author,
        thumbnail_url=thumb,
        iframe=iframe,
        link=link,
        html=html,
    )


def embeds_for_entries(session: Session, entries: Iterable[Any], settings: SiteEmbeds) -> dict[Any, dict[str, PublishedEmbed]]:
    """``{entry.id: {url as written: PublishedEmbed}}`` for a batch of entries — one cache query in all."""
    entries = list(entries)
    urls_by_entry: dict[Any, list[str]] = {}
    for entry in entries:
        et = getattr(entry, "entry_type", None)
        urls_by_entry[entry.id] = entry_embed_urls(getattr(et, "schema_json", None), entry.data_json)
    rows = cached(session, {u for urls in urls_by_entry.values() for u in urls})
    out: dict[Any, dict[str, PublishedEmbed]] = {}
    for entry_id, urls in urls_by_entry.items():
        built = {u: build_embed(u, rows.get(u), settings) for u in urls}
        out[entry_id] = {u: e for u, e in built.items() if e is not None}
    return out
