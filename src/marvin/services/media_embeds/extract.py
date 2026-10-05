"""Which links in an entry are media embeds — shared by publishing, the save-time listener, the agent
tools and the existing-content count.

Two sources, per the entry type's schema:

- **markdown fields** (unless the field sets ``autoEmbed: false``): a *bare* supported link that is a
  paragraph on its own — the line is exactly the URL, and nothing that would pull it into a
  neighbouring paragraph sits directly above or below. ``<https://…>`` and ``[text](https://…)`` stay
  links, and so does a URL inside a sentence, list item, quote, code block or fence. This mirrors what
  the site renderer (marked + GFM) sees as "a paragraph that is exactly one autolinked URL".
- **embed fields**: the field's value.

Keys are the URL exactly as written (trimmed), which is what the site looks up.
"""

from __future__ import annotations

import re
from typing import Any

from .matcher import match_url

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ATX = re.compile(r"^ {0,3}#{1,6}(\s|$)")
_THEMATIC = re.compile(r"^ {0,3}(?:(?:\*\s*){3,}|(?:_\s*){3,}|(?:-\s*){3,})$")
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)\s*$")
_BARE_URL = re.compile(r"^ {0,3}(https?://[^\s<>\"'`]+)\s*$", re.IGNORECASE)
# GFM's autolink drops these from the end of a URL, so a line ending in one isn't "exactly a URL".
_TRAILING_PUNCT = tuple(".,:;!?*_~'\")]")


def _breaks_paragraph_above(line: str | None) -> bool:
    """A line above that ends any paragraph (so the URL line starts a fresh one)."""
    return line is None or not line.strip() or bool(_ATX.match(line) or _THEMATIC.match(line) or _FENCE.match(line))


def _breaks_paragraph_below(line: str | None) -> bool:
    """A line below that doesn't continue the URL's paragraph (``---``/``===`` would make it a heading)."""
    if line is None or not line.strip():
        return True
    if _SETEXT.match(line):
        return False
    return bool(_ATX.match(line) or _FENCE.match(line) or (_THEMATIC.match(line) and "-" not in line))


def bare_urls(markdown: Any) -> list[str]:
    """Every bare link that is a paragraph on its own, in order, without duplicates (not filtered by provider)."""
    if not isinstance(markdown, str) or "http" not in markdown:
        return []
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    found: list[str] = []
    fence: str | None = None
    for i, line in enumerate(lines):
        fence_m = _FENCE.match(line)
        if fence is not None:
            if fence_m and fence_m.group(1)[0] == fence[0] and len(fence_m.group(1)) >= len(fence):
                fence = None
            continue
        if fence_m:
            fence = fence_m.group(1)
            continue
        m = _BARE_URL.match(line)
        if not m:
            continue
        url = m.group(1)
        if url.endswith(_TRAILING_PUNCT):
            continue
        above = lines[i - 1] if i > 0 else None
        below = lines[i + 1] if i + 1 < len(lines) else None
        if _breaks_paragraph_above(above) and _breaks_paragraph_below(below) and url not in found:
            found.append(url)
    return found


def _fields(schema_json: Any) -> list[dict]:
    fields = (schema_json or {}).get("fields") if isinstance(schema_json, dict) else None
    return [f for f in (fields or []) if isinstance(f, dict) and f.get("key")]


def field_embed_urls(field: dict, value: Any) -> list[str]:
    """Supported media links one field contributes (``field`` is the raw schema_json field dict)."""
    ftype = field.get("type")
    if ftype == "markdown":
        if field.get("autoEmbed", field.get("auto_embed", True)) is False:
            return []
        return [u for u in bare_urls(value) if match_url(u)]
    if ftype == "embed" and isinstance(value, str) and value.strip():
        m = match_url(value)
        allowed = field.get("providers") or None
        if m and (not allowed or m.provider.key in allowed):
            return [m.url]
    return []


def entry_embed_urls(schema_json: Any, data_json: Any) -> list[str]:
    """Supported media links an entry publishes, in field order, without duplicates."""
    data = data_json if isinstance(data_json, dict) else {}
    out: list[str] = []
    for field in _fields(schema_json):
        for url in field_embed_urls(field, data.get(field["key"])):
            if url not in out:
                out.append(url)
    return out
