"""Link → provider match, and pasted embed code → the link to store.

Matching is pure (no network): normalise the link, find the one provider whose allow-listed hosts
own it, and let that provider parse the path. Anything else — other hosts, look-alike hosts
(``youtube.com.example.org``, ``notyoutube.com``), credentials in the authority, odd ports, other
schemes — is not a media link and is never embedded.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from .providers import PROVIDERS, EmbedProvider, Target, make_link


@dataclass(frozen=True)
class Match:
    provider: EmbedProvider
    url: str
    """The link as written (trimmed) — the key it is published under."""
    target: Target


def match_url(url: str | None) -> Match | None:
    """The provider and target for a supported media link, else None."""
    link = make_link(url or "")
    if link is None:
        return None
    for provider in PROVIDERS.values():
        if provider.owns_host(link.host):
            target = provider.parse(link)
            return Match(provider=provider, url=link.raw, target=target) if target else None
    return None


_IFRAME_SRC = re.compile(r"<iframe\b[^>]*?\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.IGNORECASE | re.DOTALL)
_A_HREF = re.compile(r"<a\b[^>]*?\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.IGNORECASE | re.DOTALL)


def _first(groups: tuple) -> str:
    return html.unescape(next((g for g in groups if g), "")).strip()


def url_from_input(text: str | None) -> str | None:
    """Reduce what an editor pasted — a link, or a provider's ``<iframe>`` embed code — to the link to store.

    For embed code the iframe's ``src`` decides the provider; when the code also links the public page
    of the same item (SoundCloud and Bandcamp codes do), that page link is preferred if it can build a
    player on its own, since it reads better in the markdown and as a link card. Returns None when the
    input isn't a supported media link.
    """
    text = (text or "").strip()
    if not text:
        return None
    if "<" not in text:
        m = match_url(text)
        return m.url if m else None
    src_m = _IFRAME_SRC.search(text)
    if not src_m:
        return None
    src = _first(src_m.groups())
    if src.startswith("//"):
        src = "https:" + src
    framed = match_url(src)
    if framed is None:
        return None
    for href_groups in _A_HREF.findall(text):
        page = match_url(_first(href_groups))
        if page and page.provider.key == framed.provider.key and page.target.src:
            return page.target.canonical_url
    return framed.target.canonical_url
