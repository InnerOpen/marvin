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

Engagement — reading comments and answering them — is six more capabilities, each declared on one plugin action
(the contract every network's plugin implements; ``network`` in every output is the plugin's own name, e.g. "mastodon"):

    social.comments       read   {since?, limit? = 50, kinds? ["comment","reply","mention"]} → {items, cursor}. ``since`` is the
                                 opaque cursor the plugin returned last time; items run oldest → newest, each
                                 {id, kind, post_id, post_url, author: {id, handle, name}, text, created_at (ISO UTC), url, network}.
                                 An item's ``id`` is the ``comment_id`` every other capability takes.
    social.reply          gated  {comment_id, text, private: true, dry_run} → {replied, reply_id, private, url, network}
                                 (+ ``would_reply`` on a dry run). A mode the network can't do is refused with the SDK's
                                 IntegrationError code ``unsupported``.
    social.like           —      {comment_id} → {liked, network}
    social.hide           —      {comment_id, hidden: true} → {hidden, network}
    social.delete_comment gated  {comment_id} → {deleted, network}
    social.repost         gated  {post_id} → {reposted, url, network}
    social.message        gated  {to: {id?, handle?}, text, dry_run} → {sent, message_id, network}

"Gated" is the same rule as ``social.post``: a workflow step runs only after an Approval step (``GATED_CAPABILITIES``,
whether or not the plugin said ``requires_approval``). ``like`` and ``hide`` are easily undone moderation, so they aren't.
Posting fans out to every connected network; engagement doesn't — a comment id means something to one network only — so
a step naming one of these capabilities must also name its ``integration`` (``ENGAGEMENT_CAPABILITIES``). The one
unattended sender is the engagement engine (``social_engagement.py``), which replies under a published rule.
"""

from __future__ import annotations

import uuid
from typing import Any

SOCIAL_POST = "social.post"
SOCIAL_COMMENTS = "social.comments"
SOCIAL_REPLY = "social.reply"
SOCIAL_LIKE = "social.like"
SOCIAL_HIDE = "social.hide"
SOCIAL_DELETE_COMMENT = "social.delete_comment"
SOCIAL_REPOST = "social.repost"
SOCIAL_MESSAGE = "social.message"
SOCIAL_INBOX_ITEMS = "social.inbox_items"
"""Turn a webhook delivery (``payload``) into Social inbox items (``items``): a workflow's Run integration step that uses it has
its items kept in the integration's inbox (automation/actions/integration.py) — for a webhook the integration didn't create."""
MAX_IMAGES = 10

ENGAGEMENT_CAPABILITIES = frozenset({SOCIAL_COMMENTS, SOCIAL_REPLY, SOCIAL_LIKE, SOCIAL_HIDE, SOCIAL_DELETE_COMMENT, SOCIAL_REPOST, SOCIAL_MESSAGE})
"""Capabilities that act on one network's own ids (a comment, a post, an account): a step naming one names its
``integration`` too — it never fans out to every network the way ``social.post`` does."""
DRY_RUN_CAPABILITIES = frozenset({SOCIAL_POST, SOCIAL_REPLY, SOCIAL_MESSAGE})
"""Capabilities whose plugin action takes ``dry_run``: a workflow's dry run asks it what it would send (and nothing is sent)."""
REQUIRED_ARGS = {
    SOCIAL_REPLY: ("comment_id", "text"),
    SOCIAL_LIKE: ("comment_id",),
    SOCIAL_HIDE: ("comment_id",),
    SOCIAL_DELETE_COMMENT: ("comment_id",),
    SOCIAL_REPOST: ("post_id",),
    SOCIAL_MESSAGE: ("to", "text"),
}
"""The arguments each engagement capability can't run without (a step's ``args`` must carry each, as a value or a template)."""


class SocialPostError(Exception):
    """A social.post step's arguments can't be sent as they are (a missing asset, a private one, no text). The
    message says what to change."""


def engagement_args(capability: str, args: dict, dry_run: bool) -> dict:
    """An engagement step's arguments as the plugin takes them: the step's own, checked for what the capability needs,
    with ``dry_run`` set by the run alone for the capabilities that take it (a ``dry_run`` typed into the arguments is
    ignored, as for ``social.post``). Raises SocialPostError naming what is missing."""
    missing = [k for k in REQUIRED_ARGS.get(capability, ()) if args.get(k) in (None, "", {}, [])]
    if missing:
        raise SocialPostError(f"{capability} needs {', '.join(f'`{k}`' for k in missing)} in its args")
    if capability == SOCIAL_MESSAGE:
        to = args.get("to")
        if not isinstance(to, dict) or not (to.get("id") or to.get("handle")):
            raise SocialPostError("social.message needs `to` as an object with the person's `id` or `handle`")
    merged = {k: v for k, v in args.items() if k != "dry_run"}
    if capability in DRY_RUN_CAPABILITIES:
        merged["dry_run"] = bool(dry_run)
    return merged


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
