"""The Social inbox's store: the items the engagement poll read, kept so a person can see and act on them.

The poll (``social_engagement.py``) calls ``persist_items`` for every network read it makes — the replying read and the
announcing read alike, so the same item read twice is one row (unique on integration + item id). What it keeps:

* the normalised item as the plugin returned it (author, text, post, link), the time the network says it was written
  (``posted_at``) and the time Marvin first saw it (``first_seen_at``);
* never the account's own items (the same ``is_own`` test the engine uses to avoid answering itself) and never an item older
  than the retention window — it would be pruned at once;
* nothing else changes on a re-read: an item's text is the text first seen, and a status a person set stays.

One SELECT finds which of a batch are already stored and one multi-row INSERT writes the rest, so a poll of 50 items
costs two statements per network. A failure here is the inbox's alone: it is rolled back and logged, never the poll's.

``status`` — new → seen → liked → replied, and hidden — moves only through ``next_status``; ``mark_replied`` is how a
reply (the engine's, or a person's from the inbox) points the row at its ``social-reply-log`` entry. A daily system task
(``prune_social_inbox_items``) calls ``prune``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from marvin.core.root_logger import get_logger
from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item

from .social_rules import ITEM_KINDS, KIND_COMMENT, is_own, parse_time

logger = get_logger(__name__)

RETENTION_DAYS = 30
"""How long an item is kept (from when it was written); ``prune_social_inbox_items`` enforces it."""
NEW, SEEN, REPLIED, HIDDEN, LIKED = "new", "seen", "replied", "hidden", "liked"
STATUSES = (NEW, SEEN, LIKED, REPLIED, HIDDEN)
EVENT_SEEN, EVENT_LIKED, EVENT_REPLIED, EVENT_HIDDEN, EVENT_UNHIDDEN = "seen", "liked", "replied", "hidden", "unhidden"
TEXT_MAX = 5000
FIELD_MAX = 2000
_CHUNK = 400  # ids per IN (...): well under SQLite's variable limit


def next_status(current: str, event: str, *, replied: bool = False) -> str:
    """The status after an event. Seeing never undoes anything; a like never downgrades a reply or a hide; a reply never
    unhides; hiding wins over everything; unhiding goes back to replied (when the item was answered) or seen."""
    if event == EVENT_HIDDEN:
        return HIDDEN
    if event == EVENT_UNHIDDEN:
        return (REPLIED if replied else SEEN) if current == HIDDEN else current
    if current == HIDDEN:
        return HIDDEN
    if event == EVENT_REPLIED:
        return REPLIED
    if event == EVENT_LIKED:
        return LIKED if current in (NEW, SEEN) else current
    if event == EVENT_SEEN:
        return SEEN if current == NEW else current
    raise ValueError(f"unknown inbox event {event!r}")


def _s(value, limit: int = FIELD_MAX) -> str | None:
    return None if value in (None, "") else str(value)[:limit]


def _chunks(values: list[str]) -> Iterator[list[str]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


def _mapping(row, item: dict, posted: datetime, now: datetime) -> dict:
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    kind = str(item.get("kind") or KIND_COMMENT).lower()
    return {
        "group_id": row.group_id,
        "integration_id": row.id,
        "integration_slug": row.slug,
        "network": _s(item.get("network")) or row.provider,
        "item_id": str(item["id"])[:FIELD_MAX],
        "kind": kind if kind in ITEM_KINDS else KIND_COMMENT,
        "post_id": _s(item.get("post_id")),
        "post_url": _s(item.get("post_url")),
        "author_id": _s(author.get("id")),
        "author_handle": _s(author.get("handle")),
        "author_name": _s(author.get("name")),
        "text": str(item.get("text") or "")[:TEXT_MAX],
        "posted_at": posted,
        "url": _s(item.get("url")),
        "first_seen_at": now,
        "status": NEW,
        "reply_rehearsal": False,
    }


def persist_items(session, row, items: Iterable[dict], *, handles: set[str], ids: set[str], now: datetime) -> int:
    """Keep the items of one read that aren't stored yet (see the module docstring); returns how many were new. ``handles`` and
    ``ids`` are the integration's own account (``own_identities``). Never raises: a failure is logged and rolled back."""
    try:
        fresh = _fresh(row, items, handles, ids, now)
        if not fresh:
            return 0
        known: set[str] = set()
        for chunk in _chunks(list(fresh)):
            known.update(r[0] for r in session.query(Item.item_id).filter(Item.integration_id == row.id, Item.item_id.in_(chunk)))
        new = [m for key, m in fresh.items() if key not in known]
        if new:
            with session.begin_nested():
                session.execute(sa.insert(Item), new)
            session.commit()
        return len(new)
    except IntegrityError:  # a concurrent poll stored the same item first: its row stands
        session.rollback()
        return 0
    except Exception as e:  # noqa: BLE001 — the inbox is a convenience; the poll goes on without it
        session.rollback()
        logger.warning("social inbox: could not keep the items of %s: %s", row.slug, e)
        return 0


def _fresh(row, items: Iterable[dict], handles: set[str], ids: set[str], now: datetime) -> dict[str, dict]:
    """The row mappings worth keeping from one read, by item id: not the account's own, not older than the retention window."""
    cutoff = now - timedelta(days=RETENTION_DAYS)
    fresh: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("id") in (None, "") or is_own(item, handles, ids):
            continue
        posted = parse_time(item.get("created_at")) or now
        if posted >= cutoff:
            fresh.setdefault(str(item["id"])[:FIELD_MAX], _mapping(row, item, posted, now))
    return fresh


def mark_replied(
    session, row, item_id: str, *, log_slug: str | None, mode: str, rehearsal: bool, reply_id: str | None, when: datetime, by=None
) -> bool:
    """Point an item at the ``social-reply-log`` entry that records its reply. A real reply sets the status to replied and
    replaces a rehearsal's pointer; a rehearsal records itself only on an item with no real reply, and leaves the status.
    False when the item isn't stored (the reply predates the inbox, or the item is older than the retention window).
    Never raises: the reply is already sent and logged."""
    try:
        with session.begin_nested():
            item = session.query(Item).filter(Item.integration_id == row.id, Item.item_id == str(item_id)).one_or_none()
            if item is None:
                return False
            if rehearsal and has_live_reply(item):
                return True
            item.reply_log_slug, item.reply_mode, item.reply_rehearsal = log_slug, mode, rehearsal
            item.reply_id, item.replied_at, item.replied_by = reply_id, when, by
            if not rehearsal:
                item.status = next_status(item.status, EVENT_REPLIED)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("social inbox: could not record the reply to %s on %s: %s", item_id, row.slug, e)
        return False


def has_live_reply(item: Item) -> bool:
    """Whether a real reply was sent (a rehearsal's pointer doesn't count)."""
    return item.replied_at is not None and not item.reply_rehearsal


def prune(session, cutoff: datetime) -> int:
    """Delete the items written before ``cutoff`` (all workspaces); returns how many."""
    deleted = session.query(Item).filter(Item.posted_at < cutoff).delete(synchronize_session=False)
    session.commit()
    return deleted


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def query(
    session,
    group_id,
    *,
    integration: str | None = None,
    network: str | None = None,
    kind: str | None = None,
    status: Iterable[str] | None = None,
    text: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Item], int]:
    """A workspace's items, newest first, filtered; ``(page, total matching)``. ``text`` searches the item's text and its
    author's handle and name, case-insensitively; ``since`` / ``until`` bound the time it was written."""
    q = session.query(Item).filter(Item.group_id == group_id)
    if integration:
        q = q.filter(Item.integration_slug == integration)
    if network:
        q = q.filter(sa.func.lower(Item.network) == network.lower())
    if kind:
        q = q.filter(Item.kind == kind)
    if wanted := [s for s in (status or []) if s]:
        q = q.filter(Item.status.in_(wanted))
    if text and text.strip():
        like = _like(text.strip())
        q = q.filter(sa.or_(*(c.ilike(like, escape="\\") for c in (Item.text, Item.author_handle, Item.author_name))))
    if since is not None:
        q = q.filter(Item.posted_at >= since)
    if until is not None:
        q = q.filter(Item.posted_at <= until)
    total = q.count()
    return q.order_by(Item.posted_at.desc(), Item.id.desc()).limit(limit).offset(offset).all(), total


def new_count(session, group_id) -> int:
    """How many items are still new — the nav badge (one count on the (group, status) index)."""
    return session.query(sa.func.count(Item.id)).filter(Item.group_id == group_id, Item.status == NEW).scalar() or 0


def get_item(session, group_id, item_id) -> Item | None:
    row = session.get(Item, item_id)
    return row if row is not None and row.group_id == group_id else None
