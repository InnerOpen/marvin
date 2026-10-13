"""Media-embed tools — put a video/audio/podcast player into an entry, and preview what a link becomes.

``add_embed`` never writes the entry: it stages the change as the entry's pending suggestion (the same
review wall ``revise_entry`` uses when it stages), which an editor applies or rejects on the entry page.
It is idempotent — a link already in the field (live or staged) is reported, not added twice. In a
markdown field the link goes in as its own paragraph (that is what makes it a player); in an ``embed``
field it becomes the field's value.

``preview_embed`` is read-only for the workspace: it says whether a link is a supported media link and
what it resolves to (it may fill the platform-wide embed cache, like the editor's preview does).
"""

from __future__ import annotations

import json
import re
import uuid as _uuid

from ..entity_resolve import resolve_entity_id
from ..operations.base import ROLE_AUTHOR, ROLE_EDITOR
from .base import ToolContext, register_tool

_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")


def _summary(row, url: str) -> dict:
    """What a resolved link looks like, for the model."""
    from marvin.services.media_embeds.matcher import match_url

    m = match_url(url)
    return {
        "url": url,
        "provider": m.provider.name if m else None,
        "kind": row.kind if row is not None else (m.target.kind if m else None),
        "status": row.status if row is not None else ("ok" if m and m.target.src else "link"),
        "title": row.title if row is not None else None,
        "author": row.author_name if row is not None else None,
        "canonicalUrl": row.canonical_url if row is not None else (m.target.canonical_url if m else None),
    }


def _insert_paragraph(text: str, url: str, after_heading: str | None) -> tuple[str | None, str | None]:
    """The markdown with ``url`` added as its own paragraph: right under ``after_heading`` when given,
    else at the end. Returns (new_text, error)."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    if after_heading:
        want = after_heading.strip().lstrip("#").strip().lower()
        headings = []
        for i, line in enumerate(lines):
            hm = _HEADING.match(line)
            if not hm:
                continue
            headings.append(hm.group(2))
            if hm.group(2).strip().lower() == want:
                before = "\n".join(lines[: i + 1]).rstrip("\n")
                after = "\n".join(lines[i + 1 :]).strip("\n")
                return before + "\n\n" + url + ("\n\n" + after if after else "") + "\n", None
        return None, f"no heading '{after_heading}' in this field" + (f"; headings: {headings}" if headings else " (it has no headings)")
    body = "\n".join(lines).rstrip()
    return (body + "\n\n" if body else "") + url + "\n", None


def _pick_field(fields: list[dict], requested: str | None, provider_key: str, url: str, value_of) -> tuple[dict | None, str | None]:
    """The field to put the player in: the one asked for; else an embed field that takes this provider and is
    empty (or already holds this link) — never silently replacing another player; else the first markdown
    field with auto-embed on."""
    usable = [f for f in fields if f.get("type") in ("markdown", "embed")]
    if requested:
        field = next((f for f in fields if f.get("key") == requested), None)
        if field is None:
            return None, f"no field '{requested}'; media fields here: {[f['key'] for f in usable]}"
        if field.get("type") not in ("markdown", "embed"):
            return None, f"field '{requested}' is a {field.get('type')} field; a player goes in a markdown or embed field"
        return field, None
    for f in usable:
        current = value_of(f["key"])
        empty_or_same = not (isinstance(current, str) and current.strip()) or current.strip() == url
        if f.get("type") == "embed" and (not f.get("providers") or provider_key in f["providers"]) and empty_or_same:
            return f, None
    for f in usable:
        if f.get("type") == "markdown" and f.get("autoEmbed", True) is not False:
            return f, None
    return None, "this entry type has no markdown or embed field that can show a player"


@register_tool(
    name="add_embed",
    description=(
        "Add a video, song, album or podcast player (YouTube, Vimeo, Spotify, SoundCloud, Apple Music, Apple "
        "Podcasts, TIDAL, Simplecast, Transistor; Bandcamp from its embed code) to an EXISTING entry. Pass the "
        "link (or the provider's embed code). Optional `field` (a markdown or embed field key; default: the "
        "entry type's embed field, else its first markdown field) and `after_heading` (put it under that "
        "heading of a markdown field; default: at the end). The change is staged as a suggestion for review "
        "— nothing goes live until someone applies it. Safe to repeat: a link already there is not added "
        "again. Use preview_embed first if unsure a link is supported. Give the result's reviewLink to the "
        "user verbatim."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entry": {"type": "string", "description": "the entry by slug or id"},
            "url": {"type": "string", "description": "the media link, or the provider's <iframe> embed code"},
            "field": {"type": "string", "description": "optional markdown or embed field key"},
            "after_heading": {"type": "string", "description": "optional heading text in a markdown field to put the player under"},
        },
        "required": ["entry", "url"],
    },
    min_role=ROLE_EDITOR,
    read_only=False,
)
def add_embed(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.repos.all_repositories import get_repositories
    from marvin.services.media_embeds.cache import resolve_cached
    from marvin.services.media_embeds.extract import bare_urls
    from marvin.services.media_embeds.matcher import match_url, url_from_input
    from marvin.services.ui_links import entry_review_link

    eid = resolve_entity_id(ctx.session, ctx.group_id, "entry", args.get("entry"))
    entry = ctx.session.get(Entries, eid) if isinstance(eid, _uuid.UUID) else None
    if not entry or entry.group_id != ctx.group_id:
        return json.dumps({"error": f"entry '{args.get('entry')}' not found in this workspace"})
    url = url_from_input(str(args.get("url") or ""))
    match = match_url(url) if url else None
    if match is None:
        return json.dumps({"error": "not a supported media link or embed code (see preview_embed)"})

    entry_type = ctx.session.get(EntryTypes, entry.entry_type_id) if entry.entry_type_id else None
    fields = [f for f in ((entry_type.schema_json or {}).get("fields") or []) if isinstance(f, dict) and f.get("key")] if entry_type else []
    staged = dict(entry.suggestion_json or {})

    def value_of(key: str):
        """The field's value as the reviewer would see it: the pending suggestion's, else the live one."""
        return staged[f"data_json.{key}"] if f"data_json.{key}" in staged else (entry.data_json or {}).get(key)

    field, err = _pick_field(fields, (args.get("field") or "").strip() or None, match.provider.key, url, value_of)
    if err:
        return json.dumps({"error": err})
    key = field["key"]
    target = f"data_json.{key}"
    current = value_of(key)

    if field["type"] == "embed":
        allowed = field.get("providers") or None
        if allowed and match.provider.key not in allowed:
            return json.dumps({"error": f"field '{key}' only takes {allowed} links"})
        if isinstance(current, str) and current.strip() == url:
            new_value = None
        else:
            new_value = url
    else:
        if field.get("autoEmbed", True) is False:
            return json.dumps({"error": f"field '{key}' has auto-embed turned off, so a link there stays a link"})
        if url in bare_urls(current):
            new_value = None
        else:
            new_value, err = _insert_paragraph(current if isinstance(current, str) else "", url, (args.get("after_heading") or "").strip() or None)
            if err:
                return json.dumps({"error": err})

    row = resolve_cached(ctx.session, url)
    result = {"entryId": str(entry.id), "field": key, **_summary(row, url), "reviewLink": entry_review_link(entry.id, "Review the suggestion")}
    if new_value is None:
        return json.dumps({**result, "outcome": "already_present"})
    repos = get_repositories(ctx.session, group_id=ctx.group_id)
    repos.entries.stage_suggestion(entry.id, {target: new_value, "_meta": {"operation": "add-embed", "url": url}})
    return json.dumps({**result, "outcome": "staged"})


@register_tool(
    name="preview_embed",
    description=(
        "Check whether a link (or a provider's embed code) becomes a media player in Marvin, and what it is: "
        "provider, kind (video/audio/podcast/playlist), status (ok = a player; link = shown as a link; "
        "unavailable = private or removed), title and author. Changes no entry."
    ),
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "the media link or embed code"}},
        "required": ["url"],
    },
    min_role=ROLE_AUTHOR,
)
def preview_embed(ctx: ToolContext, args: dict) -> str:
    from marvin.services.media_embeds.cache import resolve_cached
    from marvin.services.media_embeds.matcher import url_from_input
    from marvin.services.media_embeds.providers import PROVIDERS

    url = url_from_input(str(args.get("url") or ""))
    if url is None:
        return json.dumps({"supported": False, "providers": [p.name for p in PROVIDERS.values()]})
    row = resolve_cached(ctx.session, url)
    return json.dumps({"supported": True, **_summary(row, url)})
