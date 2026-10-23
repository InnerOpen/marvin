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

``status`` — new → seen → liked → replied, and hidden — moves only through ``next_status``.

**The item is the reply log.** ``record_reply`` is how a reply (the engine's, live or rehearsal, or a person's from the inbox)
is written on its row — the mode, whether it was a rehearsal, the reply id, the text, the rule that fired, when, and who — and
a reply to an item that isn't stored yet inserts the row first, so every reply has an item. A live reply on the row is what
the engine reads as "answered" (``answered_ids``). A daily system task (``prune_social_inbox_items``) calls ``prune``.

**Pruning can't cause a second answer.** The engine answers only items under ``DEFAULT_MAX_AGE_DAYS`` (7) old, and an item is
pruned 30 days after it was written, so a pruned item is always too old to answer again. Two cases would break that, and each
is covered: a window set longer than the retention (the engine clamps ``max_age_days`` to ``MAX_ANSWER_WINDOW_DAYS``, 90), and
a network that gives an item no time (it counts as fresh forever). So ``prune`` keeps an item with a live reply for
``REPLIED_RETENTION_DAYS`` (180, longer than any answer window) instead of 30; the unanswered rest follows the 30 days.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from marvin.core.root_logger import get_logger
from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item

from .social_rules import INBOX_KINDS, KIND_COMMENT, is_own, own_identities, parse_time

logger = get_logger(__name__)

RETENTION_DAYS = 30
"""How long an item is kept (from when it was written); ``prune_social_inbox_items`` enforces it."""
REPLIED_RETENTION_DAYS = 180
"""How long an item with a live reply is kept: longer than the engine will ever answer, so a pruned item can't be answered again."""
MAX_ANSWER_WINDOW_DAYS = 90
"""The most the engine's ``max_age_days`` may be: it has to stay under ``REPLIED_RETENTION_DAYS``."""
NEW, SEEN, REPLIED, HIDDEN, LIKED = "new", "seen", "replied", "hidden", "liked"
STATUSES = (NEW, SEEN, LIKED, REPLIED, HIDDEN)
EVENT_SEEN, EVENT_LIKED, EVENT_REPLIED, EVENT_HIDDEN, EVENT_UNHIDDEN = "seen", "liked", "replied", "hidden", "unhidden"
TEXT_MAX = 5000
MAX_ATTACHMENTS = 10
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
        "kind": kind if kind in INBOX_KINDS else KIND_COMMENT,
        "post_id": _s(item.get("post_id")),
        "post_url": _s(item.get("post_url")),
        "author_id": _s(author.get("id")),
        "author_handle": _s(author.get("handle")),
        "author_name": _s(author.get("name")),
        "text": str(item.get("text") or "")[:TEXT_MAX],
        "attachments": _attachments(item.get("attachments")),
        "posted_at": posted,
        "url": _s(item.get("url")),
        "first_seen_at": now,
        "status": NEW,
        "reply_rehearsal": False,
    }


def _attachments(value) -> list[dict] | None:
    """An item's attachments as stored: each {type, url, title}, text only and capped; None when there are none."""
    if not isinstance(value, list):
        return None
    kept = [{key: _s(a.get(key)) for key in ("type", "url", "title") if _s(a.get(key))} for a in value[:MAX_ATTACHMENTS] if isinstance(a, dict)]
    return [a for a in kept if a] or None


def keep_webhook_items(session, integration_id, group_id, payload: dict, *, now: datetime | None = None) -> int:
    """A delivery to an integration's own incoming webhook, kept as inbox items: the integration (its plugin's
    ``inbox_items_from_webhook``) says what the delivery holds, and the items are stored as a poll's are — deduplicated with
    them, the account's own skipped. Returns how many were new. Never raises: the delivery and its workflows go on whatever
    happens here (a plugin that offers nothing, a connection switched off, a parsing failure)."""
    from datetime import UTC

    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return 0
    try:
        from marvin.services.integrations import IntegrationContext, build_http, get_provider

        row = session.get(IntegrationModel, integration_id)
        if row is None or row.group_id != group_id or not row.enabled:
            return 0
        provider = get_provider(row.provider)
        parse = getattr(provider, "inbox_items_from_webhook", None)
        if parse is None:
            return 0
        ctx = IntegrationContext(config=row.config or {}, secret=None, logger=logger, http=build_http())  # no secret: it parses, never calls
        items = parse(payload, ctx) or []
        if not items:
            return 0
        handles, ids = own_identities(row.config)
        return persist_items(session, row, items, handles=handles, ids=ids, now=now or datetime.now(UTC))
    except Exception as e:  # noqa: BLE001 — the inbox is a convenience; the delivery goes on without it
        session.rollback()
        logger.warning("social inbox: could not keep the items of a webhook delivery (integration %s): %s", integration_id, e)
        return 0


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


def record_reply(
    session,
    row,
    item: dict | Item,
    *,
    mode: str,
    rehearsal: bool,
    reply_id: str | None,
    text: str | None,
    rule: str | None = None,
    note: str | None = None,
    when: datetime,
    by=None,
) -> Item:
    """Write a reply on its item (and commit: it is the dedupe). ``item`` is the plugin's normalised item (inserted first when it
    isn't stored yet, of any age) or the stored row. A real reply sets the status to replied and replaces a rehearsal's record;
    a rehearsal records itself only on an item with no real reply, and leaves the status. ``rule`` is the rule entry's slug (empty
    for a person's reply, where ``by`` is the user). Raises on a database failure: the caller decides what an unrecorded reply means."""
    stored = item if isinstance(item, Item) else _stored(session, row, item, when)
    if rehearsal and has_live_reply(stored):
        return stored
    stored.reply_mode, stored.reply_rehearsal, stored.reply_id = mode, rehearsal, reply_id
    stored.reply_text, stored.reply_rule, stored.reply_note = text, rule, note
    stored.replied_at, stored.replied_by, stored.reply_log_slug = when, by, None
    if not rehearsal:
        stored.status = next_status(stored.status, EVENT_REPLIED)
    session.commit()
    return stored


def _stored(session, row, item: dict, now: datetime) -> Item:
    """The row for a plugin item, inserted when it isn't there. An item older than the retention window is stored as seen (a reply
    to something that old isn't news for the badge)."""
    found = session.query(Item).filter(Item.integration_id == row.id, Item.item_id == str(item["id"])).one_or_none()
    if found is not None:
        return found
    posted = parse_time(item.get("created_at")) or now
    mapping = _mapping(row, item, posted, now)
    if posted < now - timedelta(days=RETENTION_DAYS):
        mapping["status"] = SEEN
    try:
        with session.begin_nested():
            created = Item(session=session, **mapping)
            session.add(created)
            session.flush()
        return created
    except IntegrityError:  # a concurrent poll stored it first
        session.rollback()
        return session.query(Item).filter(Item.integration_id == row.id, Item.item_id == str(item["id"])).one()


def answered_ids(session, row, ids: list[str], *, rehearsal_counts: bool) -> set[str]:
    """Which of these item ids already have a reply: a live one, or — in rehearsal, so a dry run isn't recorded every poll — a
    rehearsal's too."""
    found: set[str] = set()
    for chunk in _chunks(list(ids)):
        q = session.query(Item.item_id).filter(Item.integration_id == row.id, Item.item_id.in_(chunk), Item.replied_at.isnot(None))
        if not rehearsal_counts:
            q = q.filter(Item.reply_rehearsal.is_(False))
        found.update(r[0] for r in q)
    return found


def has_live_reply(item: Item) -> bool:
    """Whether a real reply was sent (a rehearsal's pointer doesn't count)."""
    return item.replied_at is not None and not item.reply_rehearsal


def prune(session, cutoff: datetime, *, keep_replied_after: datetime | None = None) -> int:
    """Delete the items written before ``cutoff`` (all workspaces) — except an item with a live reply written after
    ``keep_replied_after``, which stays (see the module docstring). Returns how many."""
    q = session.query(Item).filter(Item.posted_at < cutoff)
    if keep_replied_after is not None:
        live = sa.and_(Item.replied_at.isnot(None), Item.reply_rehearsal.is_(False))
        q = q.filter(sa.not_(sa.and_(live, Item.posted_at >= keep_replied_after)))
    deleted = q.delete(synchronize_session=False)
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
    replied: bool | None = None,
    rehearsal: bool | None = None,
    text: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Item], int]:
    """A workspace's items, newest first, filtered; ``(page, total matching)``. ``text`` searches the item's text and its
    author's handle and name, case-insensitively; ``since`` / ``until`` bound the time it was written. ``replied=True`` is the
    Replies view: items with a reply, the latest reply first (``rehearsal`` narrows it to dry runs or to real replies)."""
    q = session.query(Item).filter(Item.group_id == group_id)
    if integration:
        q = q.filter(Item.integration_slug == integration)
    if network:
        q = q.filter(sa.func.lower(Item.network) == network.lower())
    if kind:
        q = q.filter(Item.kind == kind)
    if replied:
        q = q.filter(Item.replied_at.isnot(None))
        if rehearsal is not None:
            q = q.filter(Item.reply_rehearsal.is_(rehearsal))
    elif replied is False:
        q = q.filter(Item.replied_at.is_(None))
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
    order = (Item.replied_at.desc(), Item.id.desc()) if replied else (Item.posted_at.desc(), Item.id.desc())
    return q.order_by(*order).limit(limit).offset(offset).all(), total


def new_count(session, group_id, integration: str | None = None) -> int:
    """How many items are still new — the nav badge (one count on the (group, status) index), of one integration when named."""
    q = session.query(sa.func.count(Item.id)).filter(Item.group_id == group_id, Item.status == NEW)
    if integration:
        q = q.filter(Item.integration_slug == integration)
    return q.scalar() or 0


def new_counts(session, group_id) -> dict[str, int]:
    """New items per integration slug (what the sidebar shows beside each network)."""
    rows = session.query(Item.integration_slug, sa.func.count(Item.id)).filter(Item.group_id == group_id, Item.status == NEW)
    return dict(rows.group_by(Item.integration_slug).all())


def get_item(session, group_id, item_id) -> Item | None:
    row = session.get(Item, item_id)
    return row if row is not None and row.group_id == group_id else None
