"""Coalesce static-site rebuild requests per workspace.

Rebuilding a static site takes minutes and the host meters builds, but rebuild requests arrive in
bursts: a bulk edit fires a workflow per entry, and each one asks for a rebuild. So a request only
records that the workspace needs one (:func:`request_rebuild`), and the scheduler's frequent tick
sends one `webhook_triggered` per workspace (:func:`dispatch_due_rebuilds`) once requests have gone
quiet for ``QUIET_SECONDS`` — or after ``MAX_WAIT_SECONDS``, so a steady stream can't defer the
build forever. The outgoing webhooks subscribed to `webhook_triggered` (a deploy hook) do the rest.

Trailing edge on purpose: a build started while the edits are still landing would miss the later
ones and need a second build anyway. The cost is up to a minute or two before a single change
starts building; a site that must react faster to a sale reads availability live.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger
from marvin.db.models.platform.site_rebuild_requests import SiteRebuildRequestModel

logger = get_logger(__name__)

QUIET_SECONDS = 60
"""Send once no request has arrived for this long."""

MAX_WAIT_SECONDS = 600
"""Send anyway once the oldest waiting request is this old."""


def request_rebuild(session: Session, group_id: UUID, reason: str | None, *, now: datetime | None = None) -> int:
    """Record that `group_id`'s site needs a rebuild. Returns how many requests the pending rebuild now covers."""
    now = now or datetime.now(UTC)
    bumped = session.execute(
        update(SiteRebuildRequestModel)
        .where(SiteRebuildRequestModel.group_id == group_id)
        .values(last_requested_at=now, request_count=SiteRebuildRequestModel.request_count + 1, reason=reason)
    )
    if bumped.rowcount == 0:
        session.add(SiteRebuildRequestModel(session=session, group_id=group_id, first_requested_at=now, last_requested_at=now, reason=reason))
    try:
        session.commit()
    except IntegrityError:
        # Another request created the row between our UPDATE and INSERT — join it instead.
        session.rollback()
        return request_rebuild(session, group_id, reason, now=now)
    return session.execute(select(SiteRebuildRequestModel.request_count).where(SiteRebuildRequestModel.group_id == group_id)).scalar_one()


def dispatch_due_rebuilds(session: Session, send: Callable[[UUID, str], None], *, now: datetime | None = None) -> int:
    """Send every rebuild whose requests have gone quiet (or waited too long). Returns how many were sent.

    A row is claimed by deleting it *as read*: if a new request bumped it in the meantime, the delete
    matches nothing and the row waits for a later tick, so no request is ever dropped.
    """
    now = now or datetime.now(UTC)
    due = (
        session.execute(
            select(SiteRebuildRequestModel).where(
                or_(
                    SiteRebuildRequestModel.last_requested_at <= now - timedelta(seconds=QUIET_SECONDS),
                    SiteRebuildRequestModel.first_requested_at <= now - timedelta(seconds=MAX_WAIT_SECONDS),
                )
            )
        )
        .scalars()
        .all()
    )

    sent = 0
    for row in due:
        group_id, last, count, reason = row.group_id, row.last_requested_at, row.request_count, row.reason
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
            send(group_id, summary)
            sent += 1
        except Exception as e:  # noqa: BLE001 — one workspace's failure must not block the others
            logger.error("site rebuild for %s failed to dispatch: %s", group_id, e, exc_info=True)
    return sent
