"""The ``social.post`` capability — one "post this" every social network plugin maps onto its own API.

A plugin action declares ``capability="social.post"`` and ``requires_approval=True``. A workflow's integration step
names the capability (``capability: "social.post"``) with the standard arguments, and Marvin runs it on one integration
(``integration`` set) or on every connected one that offers it (no ``integration``) — services/automation/actions/integration.py.

Arguments the action receives (the step writes them in ``args``; ``per_network`` overrides them for one network):

    text      str, required — the post
    images    0–10 public https image URLs. A step may name library assets (an id or slug, or a list of them); Marvin
              hands the plugin each one's public URL, so a plugin never touches the library
    alt       list of str, one per image (filled from the assets' own alt text when the step gives none)
    link      str URL, optional
    dry_run   bool — a dry run of the workflow asks the plugin what it would post, and nothing is sent

Output: ``posted``, ``post_id``, ``url`` (the permalink), ``network`` (e.g. "instagram") and, on a dry run,
``would_post``. A plugin refuses what its network can't do (too long, needs a picture) by raising its normal action error.

Posting is public and can't be quietly undone, so a ``social.post`` action only runs after a person approved the run
(an Approval step earlier in the workflow); Marvin enforces that whether or not the plugin said ``requires_approval``.
"""

from __future__ import annotations

import uuid
from typing import Any

SOCIAL_POST = "social.post"
MAX_IMAGES = 10


class SocialPostError(Exception):
    """A social.post step's arguments can't be sent as they are (a missing asset, a private one, no text). The
    message says what to change."""


def network_overrides(per_network: Any, *names: str) -> dict:
    """The ``per_network`` arguments that apply to one network: each of ``names`` (a provider's name, then the
    integration's slug — least specific first, so the slug wins) matched case-insensitively and merged in that order."""
    if not per_network:
        return {}
    if not isinstance(per_network, dict):
        raise SocialPostError("per_network must map a network (an integration's slug or a network name) to its arguments")
    by_name = {str(k).strip().lower(): v for k, v in per_network.items()}
    merged: dict = {}
    for name in names:
        found = by_name.get(str(name or "").strip().lower())
        if found is None:
            continue
        if not isinstance(found, dict):
            raise SocialPostError(f'per_network.{name} must be an object of arguments (e.g. {{"text": "…"}})')
        merged.update(found)
    return merged


def post_args(session, group_id, args: dict, per_network: Any, *names: str) -> dict:
    """The arguments for one network: the step's ``args`` with that network's ``per_network`` over them, ``images``
    resolved to public URLs and ``alt`` filled from the assets when the step gave none. Raises SocialPostError."""
    merged = {**args, **network_overrides(per_network, *names)}
    merged = {k: v for k, v in merged.items() if v not in (None, "") or k == "text"}  # an empty link (an entry with no page yet) is none
    text = merged.get("text")
    if not isinstance(text, str) or not text.strip():
        raise SocialPostError("social.post needs `text`: what to post (it came out empty)")
    images, alts = resolve_images(session, group_id, merged.get("images"))
    merged["images"] = images
    if "alt" not in merged and any(alts):
        merged["alt"] = [a or "" for a in alts]
    return merged


def resolve_images(session, group_id, images: Any) -> tuple[list[str], list[str | None]]:
    """``images`` as public https URLs, with each one's alt text when it is a library asset (else None).

    An entry is a plain https URL (passed through), or a library asset by id or slug, or what a step's output holds:
    a collect step's asset row (its id), an entry row (its main picture, left out when it has none) or a generated
    image's ``{asset: {…}}``. A blank entry (a template that resolved to nothing, an entry with no picture) is left
    out. An asset in the Trash, one that isn't in the library (an Ask file), one that isn't a picture or a missing one is
    refused by name, never skipped — a post must not go out missing the picture a person approved.
    """
    if images in (None, "", []):
        return [], []
    items = images if isinstance(images, list) else [images]
    urls: list[str] = []
    alts: list[str | None] = []
    for item in items:
        ref = _ref(item)
        if ref is None:
            continue
        url, alt = _one(session, group_id, ref)
        urls.append(url)
        alts.append(alt)
    if len(urls) > MAX_IMAGES:
        raise SocialPostError(f"a post takes at most {MAX_IMAGES} pictures, and this one has {len(urls)}")
    return urls, alts


def _ref(item: Any) -> str | None:
    """One ``images`` entry as a string — a URL, id or slug — or None when it holds nothing."""
    if isinstance(item, dict):
        if isinstance(item.get("asset"), dict):  # a generated image kept as an asset: {asset: {id, slug, url}}
            return _ref(item["asset"])
        is_entry = "entry_type" in item or ("title" in item and "name" not in item)
        item = item.get("image") if is_entry else item.get("id") or item.get("slug") or item.get("url")
    if item in (None, ""):
        return None
    return str(item).strip() or None


def _one(session, group_id, ref: str) -> tuple[str, str | None]:
    from sqlalchemy import or_

    from marvin.db.models.platform.assets import Assets
    from marvin.services.publish_site import _names_trashed_file
    from marvin.services.storage.provider_factory import asset_public_url

    if "://" in ref or ref.startswith("/"):
        if not ref.startswith("https://"):
            raise SocialPostError(f"a picture must be a public https:// address (or a library asset's id or slug), not “{ref[:80]}”")
        if _names_trashed_file(session, group_id, ref):
            raise SocialPostError(f"“{ref[:80]}” is a picture in the Trash")
        return ref, None
    named = [Assets.slug == ref]
    try:
        named.append(Assets.id == uuid.UUID(ref))
    except ValueError:
        pass
    asset = session.query(Assets).filter(Assets.group_id == group_id, or_(*named)).first()
    if asset is None:
        raise SocialPostError(f"no asset “{ref}” in this workspace (use an asset's id or slug, or a public https:// address)")
    if asset.trashed_at is not None:
        raise SocialPostError(f"“{asset.name}” is in the Trash: restore it, or pick another picture")
    if asset.scope != "library":
        raise SocialPostError(f"“{asset.name}” is private (it isn't in the asset library), so a network can't fetch it")
    if not str(asset.mime_type or "").startswith("image/"):
        raise SocialPostError(f"“{asset.name}” ({asset.mime_type or 'unknown type'}) isn't a picture")
    url = asset_public_url(asset)
    if not url.startswith("https://"):
        raise SocialPostError(f"“{asset.name}” is served at {url[:80]}, which isn't a public https:// address a network can fetch")
    return url, asset.alt_text or None
