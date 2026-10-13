"""Public page URLs for entries.

Marvin is headless: every site decides its own routes, so Marvin cannot know where an entry is
shown unless the workspace says so. Two optional settings tell it:

- the site's address — the workspace's **Canonical URL** (``group_preferences.site_canonical_url``,
  Settings → General and Publishing → Site Configuration);
- a **page URL pattern** per entry type (``entry_types.page_url_pattern``), e.g. ``/works/{slug}``.

``entry_url`` is the one resolver every surface uses (AI tool results, the admin "View on site"
link, the publishing API). Without a pattern there is no URL anywhere — the behaviour of a
workspace that never configures this is unchanged.

Publication status is deliberately NOT consulted: the URL is where the entry *will* live, and a
draft's link is still useful to an author drafting a newsletter ahead of publishing. Callers that
show it next to an unpublished entry carry the entry's ``status`` alongside (every AI tool row
already does) and say the link is not live yet; the publishing API only serves published entries.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse

# What a pattern may reference: the entry's slug and id, and its type's slug.
PAGE_URL_PLACEHOLDERS: tuple[str, ...] = ("slug", "id", "entry_type")
# A pattern that names neither would give every entry of the type the same URL.
_IDENTIFYING_PLACEHOLDERS = frozenset({"slug", "id"})
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


def _is_absolute(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def normalize_page_url_pattern(value: str | None) -> str | None:
    """Validate a page URL pattern; blank → None (no pattern). Raises ValueError with a message
    fit for a 422 when the pattern can't produce a usable URL.

    A pattern is a site path (``/works/{slug}``) joined to the workspace's Canonical URL, or a full
    ``http(s)://`` URL for a type that lives on another host (``https://shop.example.com/p/{slug}``).
    """
    if value is None:
        return None
    pattern = value.strip()
    if not pattern:
        return None
    if not (pattern.startswith("/") or _is_absolute(pattern)):
        raise ValueError("Page URL pattern must start with / (a path on the site) or http(s):// (a full URL).")
    names = _PLACEHOLDER.findall(pattern)
    unknown = sorted({n for n in names if n not in PAGE_URL_PLACEHOLDERS})
    if unknown:
        allowed = ", ".join(f"{{{p}}}" for p in PAGE_URL_PLACEHOLDERS)
        raise ValueError(f"Unknown placeholder(s) {', '.join(f'{{{n}}}' for n in unknown)} — use {allowed}.")
    literal = _PLACEHOLDER.sub("", pattern)
    if "{" in literal or "}" in literal:
        raise ValueError("Page URL pattern has an unmatched { or }.")
    if not _IDENTIFYING_PLACEHOLDERS & set(names):
        raise ValueError("Page URL pattern must include {slug} or {id} so each entry gets its own URL.")
    return pattern


def normalize_site_url(value: str | None) -> str | None:
    """The workspace's site address as a join-ready base (no trailing slash), or None when it is
    unset or not an absolute http(s) URL — a relative or malformed value can't anchor a link."""
    base = (value or "").strip().rstrip("/")
    return base if base and _is_absolute(base) else None


def site_base_url(session, group_id) -> str | None:
    """The workspace's site address (its Canonical URL), normalized; None when not configured.
    One query — callers resolving many entries fetch it once and pass it to ``entry_url``."""
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    raw = session.query(GroupPreferencesModel.site_canonical_url).filter(GroupPreferencesModel.group_id == group_id).scalar()
    return normalize_site_url(raw)


def entry_url(entry, *, absolute: bool, site_url: str | None = None, entry_type=None) -> str | None:
    """The URL of ``entry``'s page on the workspace's site, or None when it can't be built.

    ``entry`` needs ``slug`` and ``id``; its type comes from ``entry_type`` or ``entry.entry_type``.
    ``absolute=False`` returns the site path (``/works/blue-heron``); ``absolute=True`` joins it to
    ``site_url`` (from ``site_base_url``). A pattern that is itself a full URL is returned as-is
    either way. None when: the type has no pattern, the type is marked not routable, a value the
    pattern needs is empty, or ``absolute`` is asked for without a ``site_url``. Status is not
    checked — see the module docstring.
    """
    et = entry_type if entry_type is not None else getattr(entry, "entry_type", None)
    pattern = getattr(et, "page_url_pattern", None) if et is not None else None
    if not pattern:
        return None
    capabilities = getattr(et, "capabilities_json", None)
    if isinstance(capabilities, dict) and capabilities.get("routable") is False:
        return None

    entry_id = getattr(entry, "id", None)
    values = {
        "slug": (getattr(entry, "slug", None) or "").strip(),
        "id": str(entry_id) if entry_id else "",
        "entry_type": (getattr(et, "slug", None) or "").strip(),
    }
    missing = False

    def _fill(match: re.Match) -> str:
        nonlocal missing
        value = values.get(match.group(1), "")
        if not value:
            missing = True
        return quote(value, safe="")

    url = _PLACEHOLDER.sub(_fill, pattern)
    if missing:
        return None
    if _is_absolute(url) or not absolute:
        return url
    base = normalize_site_url(site_url)
    return f"{base}{url}" if base else None


def best_entry_url(entry, site_url: str | None, *, entry_type=None) -> str | None:
    """Absolute when the workspace has a site address, otherwise the site path — what a caller
    that wants "the most useful link available" (AI tool results, the publishing API) shows."""
    base = normalize_site_url(site_url)
    return entry_url(entry, absolute=bool(base), site_url=base, entry_type=entry_type)
