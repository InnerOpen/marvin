"""The Social auto-reply rules as a network's page lists them: the rule entries that apply to one integration (or to all of them),
and the two things the page does with them — start a new rule (a draft, defaulting to that network) and publish or unpublish one.

The rules stay entries of the internal ``social-auto-reply`` type (services/entry_listing.py): they are edited with the normal
entry editor, reached from Social › a network › Rules, and a published rule is what the engine answers under. Instagram's older
``ig-auto-reply`` entries are listed too (they fire, read as rules for network instagram), marked ``legacy``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .social_rules import IG_NETWORK, IG_RULE_TYPE, RULE_TYPE, _words
from .social_setup import ensure_rule_type

EDITABLE_STATUSES = ("draft", "inbox", "needs_review", "approved", "published")


@dataclass
class RuleRow:
    id: object
    slug: str
    title: str
    status: str
    keywords: list[str]
    reply: str
    networks: list[str]
    """Integration slugs (or network names) the rule names; empty means every network."""
    post: str
    reply_as: str
    also_like: bool
    kinds: list[str]
    legacy: bool = False
    path: str = field(default="")

    @property
    def published(self) -> bool:
        return self.status == "published"

    @property
    def all_networks(self) -> bool:
        return not self.networks


def _row(entry, type_slug: str) -> RuleRow:
    data = entry.data_json or {}
    legacy = type_slug == IG_RULE_TYPE
    return RuleRow(
        id=entry.id,
        slug=entry.slug,
        title=entry.title or entry.slug,
        status=entry.status,
        keywords=_words(data.get("keywords")),
        reply=str(data.get("reply") or ""),
        networks=[IG_NETWORK] if legacy else [n.lower().lstrip("@") for n in _words(data.get("networks"))],
        post=str(data.get("post_id" if legacy else "post") or "").strip(),
        reply_as="private" if legacy else str(data.get("reply_as") or "private"),
        also_like=False if legacy else data.get("also_like") in (True, "true", "True", 1, "1", "yes"),
        kinds=["comment", "reply"] if legacy else (_words(data.get("kinds")) or ["comment", "reply"]),
        legacy=legacy,
        path=f"/workspace/entries/{entry.id}",
    )


def list_rules(session, group_id, *, integration=None) -> list[RuleRow]:
    """The workspace's rules, oldest first (the order the engine breaks ties in). With an ``integration`` row: the rules that apply
    to it — the ones naming its slug or network, and the ones that name no network. Trashed and archived rules aren't listed."""
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes

    q = (
        session.query(Entries, EntryTypes.slug)
        .join(EntryTypes, Entries.entry_type_id == EntryTypes.id)
        .filter(Entries.group_id == group_id, EntryTypes.slug.in_([RULE_TYPE, IG_RULE_TYPE]), Entries.status.in_(EDITABLE_STATUSES))
        .order_by(Entries.created_at.asc(), Entries.id.asc())
    )
    rows = [_row(entry, type_slug) for entry, type_slug in q]
    if integration is None:
        return rows
    mine = {integration.slug.lower(), integration.provider.lower()}
    return [r for r in rows if not r.networks or set(r.networks) & mine]


def create_rule(session, group_id, *, integration=None, user_id=None) -> RuleRow:
    """A new blank rule as a draft — a draft never fires — made for ``integration`` (its slug in ``networks``) or, with none, for
    every network. The editor (``path``) is where the keywords and reply are written and the rule is published."""
    from marvin.services.entries.entry_service import EntryService

    type_id = ensure_rule_type(session, group_id)
    data = {"keywords": "", "reply": "", "networks": integration.slug if integration is not None else "", "post": "",
            "reply_as": "private", "also_like": False, "kinds": "comment, reply"}  # fmt: skip
    where = f"({integration.name})" if integration is not None else "(every network)"
    fields = {
        "entry_type_id": type_id,
        "title": f"New rule {where}",
        "slug": f"social-rule-{uuid.uuid4().hex[:8]}",
        "status": "draft",
        "data_json": data,
    }
    if user_id:
        fields["created_by"] = user_id
    entry = EntryService(session, group_id, integration_id="social_rules", actor_id=user_id).create(fields)
    session.commit()
    return RuleRow(
        id=entry.id, slug=entry.slug, title=entry.title, status=entry.status, keywords=[], reply="",
        networks=[integration.slug.lower()] if integration is not None else [], post="", reply_as="private", also_like=False,
        kinds=["comment", "reply"], path=f"/workspace/entries/{entry.id}",
    )  # fmt: skip


def is_rule_entry(session, group_id, entry_id) -> bool:
    """Whether the entry is one of the workspace's auto-reply rules (either type)."""
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes

    found = (
        session.query(Entries.id)
        .join(EntryTypes, Entries.entry_type_id == EntryTypes.id)
        .filter(Entries.id == entry_id, Entries.group_id == group_id, EntryTypes.slug.in_([RULE_TYPE, IG_RULE_TYPE]))
        .first()
    )
    return found is not None
