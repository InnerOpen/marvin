"""Resolve a media link: match it, build the player src, and ask the provider's oEmbed for the rest.

oEmbed goes through core's guarded ``MarvinHttpHelper`` (public hosts only, re-checked on redirect;
256 KB cap; 5 s timeout; ``marvin-cms/embeds`` User-Agent). From the reply Marvin keeps only plain
facts — title, author, thumbnail URL — and, for providers whose link doesn't carry the id, the iframe
``src`` out of the reply's HTML once its host and path pass that provider's own parser; the src is then
rebuilt by Marvin. The provider's HTML itself is never kept.

Outcomes:
  ``ok``          — Marvin has a player src (from the link, or validated out of oEmbed);
  ``link``        — no safe player (link-only provider, or oEmbed failed for a link that needs it);
  ``unavailable`` — the provider answered 401/403/404 (private, removed or region-blocked).
A transient failure (timeout, 5xx, bad JSON) keeps a src built from the link as ``ok``; it is cached
for a day only, so the next save tries again.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Protocol
from urllib.parse import quote

from marvin.core.root_logger import get_logger

from .matcher import Match, match_url
from .providers import make_link

USER_AGENT = "marvin-cms/embeds"
MAX_BYTES = 256 * 1024
TIMEOUT_SECONDS = 5.0

logger = get_logger()


class _HttpLike(Protocol):
    def get(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 15): ...


@dataclass
class ResolvedEmbed:
    url: str
    provider: str
    kind: str
    status: str
    canonical_url: str
    embed_src: str | None = None
    title: str | None = None
    author_name: str | None = None
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None
    error: str | None = None
    settled: bool = False
    """True once the provider has answered (or has no oEmbed): the result can be cached for long."""


def default_http() -> _HttpLike:
    from marvin.services.integrations.http_client import MarvinHttpHelper

    return MarvinHttpHelper(max_bytes=MAX_BYTES)


def fetch_enabled() -> bool:
    from marvin.core.config import get_app_settings

    return bool(getattr(get_app_settings(), "MEDIA_EMBEDS_FETCH_ENABLED", True))


def from_match(match: Match) -> ResolvedEmbed:
    """What the link alone gives — no network. ``ok`` when the link carries enough to build the player."""
    t = match.target
    return ResolvedEmbed(
        url=match.url,
        provider=match.provider.key,
        kind=t.kind,
        status="ok" if t.src else "link",
        canonical_url=t.canonical_url,
        embed_src=t.src,
        height=t.height,
        aspect_ratio=t.aspect_ratio,
    )


_IFRAME_SRC = re.compile(r"<iframe\b[^>]*?\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE | re.DOTALL)


def _clean_text(value: object, limit: int = 500) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(unescape(value).split())
    return value[:limit] or None


def _clean_url(value: object) -> str | None:
    """Only a plain public https URL survives (a thumbnail is shown as-is by sites)."""
    if not isinstance(value, str):
        return None
    link = make_link(value)
    return link.raw if link and link.scheme == "https" else None


def _int(value: object) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 10000 else None


def resolve(url: str, *, http: _HttpLike | None = None, fetch: bool | None = None) -> ResolvedEmbed | None:
    """Resolve one link. None when it isn't a supported media link. ``fetch=False`` skips oEmbed."""
    match = match_url(url)
    if match is None:
        return None
    result = from_match(match)
    provider = match.provider
    if not provider.oembed:
        result.settled = True
        return result
    if fetch is None:
        fetch = fetch_enabled()
    if not fetch:
        return result

    endpoint = provider.oembed.format(url=quote(match.target.canonical_url, safe=""))
    try:
        client = http or default_http()
        resp = client.get(endpoint, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=TIMEOUT_SECONDS)
    except Exception as e:  # SSRF refusal, DNS failure, timeout, size cap — all transient from here
        result.error = f"oEmbed request failed: {type(e).__name__}: {e}"[:500]
        return result

    status_code = getattr(resp, "status_code", 0)
    if status_code in (401, 403, 404):
        result.status = "unavailable"
        result.embed_src = None
        result.error = f"{provider.name} says this media is unavailable (HTTP {status_code})."
        result.settled = True
        return result
    if not 200 <= status_code < 300:
        result.error = f"oEmbed answered HTTP {status_code}"
        return result
    try:
        data = json.loads(resp.content)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (ValueError, TypeError) as e:
        result.error = f"oEmbed reply was not JSON: {e}"[:500]
        return result

    result.title = _clean_text(data.get("title"))
    result.author_name = _clean_text(data.get("author_name"), 200)
    result.thumbnail_url = _clean_url(data.get("thumbnail_url"))
    result.width = _int(data.get("width"))
    result.settled = True

    if result.embed_src is None and provider.from_oembed_src is not None:
        # The id lives only in the provider's player src: take it out of their HTML (or Spotify's
        # iframe_url), check it with the provider's own parser, and rebuild it.
        candidates = [data.get("iframe_url")] + [next((g for g in m.groups() if g), None) for m in _IFRAME_SRC.finditer(str(data.get("html") or ""))]
        for cand in candidates:
            link = make_link(unescape(cand)) if isinstance(cand, str) else None
            target = provider.from_oembed_src(link) if link and provider.owns_host(link.host) else None
            if target and target.src and provider.frame_host_ok(target.src):
                result.embed_src = target.src
                result.kind = target.kind
                result.height = target.height
                result.aspect_ratio = target.aspect_ratio
                result.status = "ok"
                break
        else:
            result.status = "link"
            result.error = f"{provider.name}'s oEmbed reply had no player Marvin recognises."
    return result
