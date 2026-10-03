"""Coalesce static-site rebuild requests per workspace.

Rebuilding a static site takes minutes and the host meters builds, but rebuild requests arrive in
bursts: a bulk edit fires a workflow per entry, and each one asks for a rebuild. So a request only
records that the workspace needs one (:func:`request_rebuild`), and the scheduler's frequent tick
sends one `webhook_triggered` per workspace (:func:`dispatch_due_rebuilds`) once requests have gone
quiet for SITE_REBUILD_QUIET_SECONDS — or after SITE_REBUILD_MAX_WAIT_SECONDS, so a steady stream
can't defer the build forever (both app settings, i.e. env vars). The outgoing webhooks subscribed to `webhook_triggered` (a deploy hook) do the rest.

Trailing edge on purpose: a build started while the edits are still landing would miss the later
ones and need a second build anyway. The cost is up to a minute or two before a single change
starts building; a site that must react faster to a sale reads availability live.

Each request can also say what changed (:func:`rebuild_change`); the pending row keeps a short list
of them so the `webhook_triggered` event — and the admin's "Site rebuild" toast — can show what one
build covers.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marvin.core.config import get_app_settings
from marvin.core.root_logger import get_logger
from marvin.db.models.platform.site_rebuild_requests import SiteRebuildRequestModel

logger = get_logger(__name__)


# A rebuild lists at most this many changes (the newest); `request_count` still counts every request.
MAX_LISTED_CHANGES = 50
MAX_CHANGE_LABEL_CHARS = 200


def rebuild_change(label: str, event: str | None = None, entity_type: str | None = None, entity_id: Any = None) -> dict:
    """One line of what a rebuild covers, as :func:`request_rebuild` records it."""
    return {
        "label": str(label)[:MAX_CHANGE_LABEL_CHARS],
        "event": event,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
    }


def _change_key(item: dict) -> tuple:
    # The same entry edited twice is one change; without an entity, the same wording is.
    return ("entity", item.get("entity_type"), item["entity_id"]) if item.get("entity_id") else ("label", item.get("label"))


def _with_change(changes: list[dict] | None, item: dict) -> list[dict]:
    """`changes` with `item` as the newest, an older line for the same thing dropped, capped to the newest."""
    key = _change_key(item)
    return [*(c for c in changes or [] if _change_key(c) != key), item][-MAX_LISTED_CHANGES:]


def request_rebuild(session: Session, group_id: UUID, reason: str | None, *, change: dict | None = None, now: datetime | None = None) -> int:
    """Record that `group_id`'s site needs a rebuild (and, optionally, what changed — see :func:`rebuild_change`).

    Returns how many requests the pending rebuild now covers.
    """
    now = now or datetime.now(UTC)
    bumped = session.execute(
        update(SiteRebuildRequestModel)
        .where(SiteRebuildRequestModel.group_id == group_id)
        .values(last_requested_at=now, request_count=SiteRebuildRequestModel.request_count + 1, reason=reason)
    )
    if bumped.rowcount == 0:
        session.add(
            SiteRebuildRequestModel(
                session=session,
                group_id=group_id,
                first_requested_at=now,
                last_requested_at=now,
                reason=reason,
                changes=[change] if change else None,
            )
        )
    elif change:
        # Read-modify-write, unlike the count: done after our UPDATE in the same transaction, so on
        # Postgres that UPDATE's row lock orders concurrent appends — but if two ever interleave, the
        # worst case is one missing line in the list, never a lost count or a lost rebuild.
        listed = session.execute(select(SiteRebuildRequestModel.changes).where(SiteRebuildRequestModel.group_id == group_id)).scalar_one()
        session.execute(
            update(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == group_id).values(changes=_with_change(listed, change))
        )
    try:
        session.commit()
    except IntegrityError:
        # Another request created the row between our UPDATE and INSERT — join it instead.
        session.rollback()
        return request_rebuild(session, group_id, reason, change=change, now=now)
    return session.execute(select(SiteRebuildRequestModel.request_count).where(SiteRebuildRequestModel.group_id == group_id)).scalar_one()


def dispatch_due_rebuilds(
    session: Session,
    send: Callable[[UUID, str, list[dict], int], None],
    *,
    now: datetime | None = None,
    quiet_seconds: int | None = None,
    max_wait_seconds: int | None = None,
) -> int:
    """Send every rebuild whose requests have gone quiet (or waited too long). Returns how many were sent.

    `send(group_id, summary, changes, request_count)` gets the row's listed changes (newest last).

    A row is claimed by deleting it *as read*: if a new request bumped it in the meantime, the delete
    matches nothing and the row waits for a later tick, so no request is ever dropped.
    """
    now = now or datetime.now(UTC)
    settings = get_app_settings()
    quiet = settings.SITE_REBUILD_QUIET_SECONDS if quiet_seconds is None else quiet_seconds
    max_wait = settings.SITE_REBUILD_MAX_WAIT_SECONDS if max_wait_seconds is None else max_wait_seconds
    due = (
        session.execute(
            select(SiteRebuildRequestModel).where(
                or_(
                    SiteRebuildRequestModel.last_requested_at <= now - timedelta(seconds=quiet),
                    SiteRebuildRequestModel.first_requested_at <= now - timedelta(seconds=max_wait),
                )
            )
        )
        .scalars()
        .all()
    )

    sent = 0
    for row in due:
        group_id, last, count, reason, changes = row.group_id, row.last_requested_at, row.request_count, row.reason, row.changes or []
        claimed = session.execute(
            delete(SiteRebuildRequestModel).where(
                SiteRebuildRequestModel.group_id == group_id,
                SiteRebuildRequestModel.last_requested_at == last,
            )
        )
        session.commit()
        if claimed.rowcount != 1:
            continue
        latest = reason or "requested"
        summary = latest if count == 1 else f"{count} requests, latest: {latest}"
        try:
            send(group_id, summary, changes, count)
            sent += 1
        except Exception as e:  # noqa: BLE001 — one workspace's failure must not block the others
            logger.error("site rebuild for %s failed to dispatch: %s", group_id, e, exc_info=True)
    return sent
