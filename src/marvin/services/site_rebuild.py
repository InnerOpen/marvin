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

The request that opens a batch also announces it (`site_rebuild_queued`, with both windows), so the
admin sees "queued — building in about a minute" instead of silence until it's sent. Only the
opening one: a bulk edit can add hundreds of requests to the same batch.
"""

from collections.abc import Callable
from dataclasses import dataclass
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


# The event a site's deploy hook subscribes to — what a sent rebuild goes out as.
REBUILD_EVENT = "webhook_triggered"


@dataclass(frozen=True)
class DeployTarget:
    """Something that builds the site when a rebuild is sent: an outgoing webhook (a host's deploy hook)
    or an enabled integration whose action is subscribed to `webhook_triggered`."""

    kind: str
    """"webhook" or "integration"."""
    id: UUID
    name: str | None = None
    provider: str | None = None
    """The integration's provider (e.g. cloudflare_pages); None for a webhook."""
    action: str | None = None
    """The integration action the rebuild runs (e.g. deploy); None for a webhook."""


def deploy_targets(session: Session, group_id: UUID) -> list[DeployTarget]:
    """Everything a sent rebuild reaches: the enabled event-driven outgoing webhooks on `webhook_triggered`
    and the enabled integrations with an enabled action subscribed to it — the same ones the event bus
    delivers to. Empty means a rebuild builds nothing. Sorted by kind and name, one per webhook or integration.
    """
    from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.groups.webhooks import GroupWebhooksModel

    hooks = session.execute(select(GroupWebhooksModel).where(GroupWebhooksModel.group_id == group_id, GroupWebhooksModel.enabled.is_(True))).scalars()
    targets = {
        hook.id: DeployTarget("webhook", hook.id, hook.name)
        for hook in hooks
        if REBUILD_EVENT in (hook.subscribed_events or []) and getattr(hook.webhook_type, "value", None) == "event_driven"
    }
    subscribed = session.execute(
        select(IntegrationModel, IntegrationEventSubscriptionModel.action)
        .join(IntegrationModel, IntegrationModel.id == IntegrationEventSubscriptionModel.integration_id)
        .where(
            IntegrationEventSubscriptionModel.group_id == group_id,
            IntegrationEventSubscriptionModel.event_type == REBUILD_EVENT,
            IntegrationEventSubscriptionModel.enabled.is_(True),
            IntegrationModel.enabled.is_(True),
        )
    ).all()
    for integration, action in subscribed:
        targets.setdefault(integration.id, DeployTarget("integration", integration.id, integration.name, integration.provider, action))
    return sorted(targets.values(), key=lambda t: (t.kind, t.name or "", str(t.id)))


def deploy_target(session: Session, group_id: UUID) -> tuple[str, UUID] | None:
    """What builds this workspace's site — ``("webhook", id)`` for an outgoing webhook (deploy hook) on
    `webhook_triggered`, ``("integration", id)`` for an integration action wired to it — or None when
    there is none or more than one, so a rebuild or deploy event never names the wrong one.

    The site pipeline's events (site_rebuild_queued, webhook_triggered, site_deployment_*) are about
    this target; the deployment id, when a host reports one, stays in the event's data.
    """
    try:
        targets = deploy_targets(session, group_id)
    except Exception as e:  # noqa: BLE001 — naming the target is a nicety; the event goes out regardless
        logger.warning("could not resolve the deploy target for %s: %s", group_id, e)
        return None
    return (targets[0].kind, targets[0].id) if len(targets) == 1 else None


def deploy_target_fields(group_id: UUID) -> dict:
    """``entity_type``/``entity_id`` dispatch kwargs naming the workspace's deploy target (empty when none).

    Looked up in a session of its own, so a failed lookup can never spoil the caller's transaction.
    """
    from marvin.db.db_setup import session_context

    try:
        with session_context() as session:
            target = deploy_target(session, group_id)
    except Exception as e:  # noqa: BLE001 — as in deploy_target: never block the event
        logger.warning("could not open a session to resolve the deploy target for %s: %s", group_id, e)
        target = None
    return {"entity_type": target[0], "entity_id": target[1]} if target else {}


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
    opened = bumped.rowcount == 0
    if opened:
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
    if opened:
        _announce_queued(group_id, reason, change, now)
    return session.execute(select(SiteRebuildRequestModel.request_count).where(SiteRebuildRequestModel.group_id == group_id)).scalar_one()


def pending_rebuild(session: Session, group_id: UUID) -> SiteRebuildRequestModel | None:
    """The workspace's queued rebuild that hasn't been sent yet, if any."""
    return session.execute(select(SiteRebuildRequestModel).where(SiteRebuildRequestModel.group_id == group_id)).scalar_one_or_none()


def expected_send_at(first_requested_at: datetime, last_requested_at: datetime) -> datetime:
    """When a queued rebuild goes out if nothing else joins it: once requests have been quiet for
    SITE_REBUILD_QUIET_SECONDS, but no later than SITE_REBUILD_MAX_WAIT_SECONDS after the first (the
    scheduler sends it on its next tick after that)."""
    settings = get_app_settings()
    return min(
        last_requested_at + timedelta(seconds=settings.SITE_REBUILD_QUIET_SECONDS),
        first_requested_at + timedelta(seconds=settings.SITE_REBUILD_MAX_WAIT_SECONDS),
    )


def _announce_queued(group_id: UUID, reason: str | None, change: dict | None, queued_at: datetime) -> None:
    """Dispatch `site_rebuild_queued` for a batch that just opened. Best-effort — the request is already saved."""
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventSiteRebuildQueuedData, EventTypes, SiteRebuildChange

    settings = get_app_settings()
    quiet, max_wait = settings.SITE_REBUILD_QUIET_SECONDS, settings.SITE_REBUILD_MAX_WAIT_SECONDS
    try:
        EventBusService(bg_tasks=None).dispatch(
            integration_id="site_rebuild",
            group_id=group_id,
            event_type=EventTypes.site_rebuild_queued,
            document_data=EventSiteRebuildQueuedData(
                workspace_id=group_id,
                reason=reason,
                change=SiteRebuildChange.model_validate(change) if change else None,
                quiet_seconds=quiet,
                max_wait_seconds=max_wait,
                queued_at=queued_at,
                expected_send_at=queued_at + timedelta(seconds=quiet),
            ),
            message=f"Site rebuild queued: {(change or {}).get('label') or reason or 'requested'}",
            **deploy_target_fields(group_id),
        )
    except Exception as e:  # noqa: BLE001 — announcing must never lose the queued rebuild
        logger.warning("could not announce the queued site rebuild for %s: %s", group_id, e)


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
