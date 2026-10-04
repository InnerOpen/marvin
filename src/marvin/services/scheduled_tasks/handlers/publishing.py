"""
Publishing task handlers for content management.

These handlers manage scheduled publishing, unpublishing, and site rebuild triggers.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.db.models.groups.preferences import GroupPreferencesModel
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.schemas.platform import EntryUpdate
from marvin.services.entries import EntryService
from marvin.services.entries.scheduled_block import (
    APPROVAL_REASON,
    WAITING_FOR_APPROVAL,
    WAITING_FOR_REQUIREMENTS,
    approval_issue,
    block_record,
)
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import EventSiteRebuildData, EventTypes, SiteRebuildChange

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger(__name__)

# Source tag on the entry events a scheduled publish/expiry emits.
INTEGRATION_ID = "scheduled_tasks"
# Entries named in a run summary before it says "and N more".
SUMMARY_NAME_LIMIT = 5
# What EntryService's publish gate raises for an entry it won't publish: missing required
# fields/assets/tags, or an expiration date that has already passed.
PUBLISH_REFUSED_STATUS_CODE = 422


class _StatusChanger:
    """Change an entry's status the way a manual status change does: through EntryService, so the
    run emits the same events (entry_updated, then entry_published / entry_unpublished /
    entry_archived, carrying the entry's id and type) and gets the same repository side effects.
    Smart collections, workflows, site rebuilds and indexing all key on those events.

    A platform-wide run spans workspaces, so there's one service per entry's workspace and each
    event carries that entry's group_id. No actor: the system made the change.
    """

    def __init__(self, session, event_bus: EventBusService) -> None:
        self._session = session
        self._event_bus = event_bus
        self._services: dict[UUID, EntryService] = {}

    def _service(self, group_id: UUID) -> EntryService:
        service = self._services.get(group_id)
        if service is None:
            service = EntryService(self._session, group_id, event_bus=self._event_bus, integration_id=INTEGRATION_ID)
            self._services[group_id] = service
        return service

    def set_status(self, entry: Entries, status: str, **changes) -> None:
        """Set the status, plus any other field `changes` made in the same update (one
        entry_updated event)."""
        self._service(entry.group_id).update(entry.id, EntryUpdate(status=status, **changes))

    def hold(self, entry: Entries, waiting_for: str, reason: str, issues: list[str], now: datetime) -> None:
        """Record why a due entry is being held back (Entries.scheduled_publish_blocked) and emit
        entry_scheduled_publish_blocked the first time this block is seen — not on every run. Written
        directly, not as an entry update: it's the task's bookkeeping, not an edit to react to."""
        previous = entry.scheduled_publish_blocked
        record = block_record(waiting_for, reason, issues, previous, now)
        notify = not record["notified"]
        record["notified"] = True
        if record != previous:
            entry.scheduled_publish_blocked = record
            self._session.commit()
        if notify:
            self._service(entry.group_id).emit_scheduled_publish_blocked(entry, record)


def _entries(n: int) -> str:
    return f"{n} entr{'y' if n == 1 else 'ies'}"


def _limited(items: list[str], sep: str = ", ") -> str:
    shown = sep.join(items[:SUMMARY_NAME_LIMIT])
    extra = len(items) - SUMMARY_NAME_LIMIT
    return f"{shown} and {extra} more" if extra > 0 else shown


def _titles(titles: list[str]) -> str:
    return _limited([f"'{t}'" for t in titles])


def _refusal_issues(error: HTTPException) -> list[str]:
    detail = error.detail if isinstance(error.detail, dict) else {}
    return [str(i) for i in detail.get("issues") or []]


def _refusal_reason(error: HTTPException) -> str:
    detail = error.detail if isinstance(error.detail, dict) else {}
    return ", ".join(_refusal_issues(error)) or str(detail.get("message") or error.detail)


def _approval_only_workspaces(session, workspace_ids: set[UUID]) -> set[UUID]:
    """The workspaces among `workspace_ids` that publish only approved entries on schedule."""
    if not workspace_ids:
        return set()
    rows = session.query(GroupPreferencesModel.group_id).filter(
        GroupPreferencesModel.group_id.in_(workspace_ids),
        GroupPreferencesModel.scheduled_publish_requires_approval.is_(True),
    )
    return {row[0] for row in rows}


class PublishScheduledEntriesHandler(ScheduledTaskHandler):
    """
    Publish entries with publish_at <= now, scoped to the task's workspace (every workspace for
    the built-in system task).

    Each entry is published as a manual status change would publish it (EntryService), so the
    same events fire and the same rules apply:
    - publishing consumes the schedule (publish_at is cleared), so an entry unpublished afterwards
      stays unpublished instead of going live again on the next run;
    - a published_at already set (a backdated import) is kept;
    - an entry that fails its type's completeness check, or whose expiration date has already
      passed, is skipped and keeps its schedule, so it shows as overdue and goes out on the first
      run after it's fixed. The others still publish.
    Archived entries are skipped: an old schedule must not resurrect them.

    A workspace with "Scheduled publish only for approved entries" on (preferences.
    scheduled_publish_requires_approval) gets only its `approved` due entries published; the others
    keep their schedule and wait. Every entry held back, for either reason, gets the reason recorded
    on it (the editor shows it next to Scheduled Publish) and one entry_scheduled_publish_blocked
    event per distinct reason, which the activity toaster shows (services/entries/scheduled_block.py).

    Configuration (task_config):
    - dry_run: bool (default: False) - If true, log what would be published
    """

    name = "Publish Scheduled Entries"
    description = "Publish entries whose publish_at time has arrived"
    can_run_platform_wide = True

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        dry_run = task.task_config.get("dry_run", False)
        workspace_id = UUID(str(task.group_id)) if task.group_id else None
        scope_label = str(workspace_id) if workspace_id else "all workspaces"

        published: list[str] = []
        skipped: list[str] = []
        waiting: list[str] = []
        with session_context() as session:
            q = session.query(Entries).filter(
                Entries.publish_at <= datetime.now(UTC),
                Entries.status.notin_(("published", "archived")),
            )
            if workspace_id:
                q = q.filter(Entries.group_id == workspace_id)
            due = q.all()
            logger.debug("Found %d entries to publish in %s (dry_run=%s)", len(due), scope_label, dry_run)

            changer = _StatusChanger(session, event_bus)
            approval_only = _approval_only_workspaces(session, {entry.group_id for entry in due})
            now = datetime.now(UTC)
            for entry in due:
                entry_id, title = entry.id, entry.title
                if entry.group_id in approval_only and entry.status != "approved":
                    logger.info("Scheduled publish of '%s' (id=%s) is waiting for approval (status %s)", title, entry_id, entry.status)
                    if not dry_run:
                        changer.hold(entry, WAITING_FOR_APPROVAL, APPROVAL_REASON, [approval_issue(entry.status)], now)
                    waiting.append(title)
                    continue
                if dry_run:
                    logger.info("Would publish: %s (id=%s, publish_at=%s)", title, entry_id, entry.publish_at)
                    published.append(title)
                    continue
                try:
                    changer.set_status(entry, "published")
                except HTTPException as e:
                    if e.status_code != PUBLISH_REFUSED_STATUS_CODE:
                        raise
                    reason = _refusal_reason(e)
                    logger.warning("Scheduled publish skipped entry '%s' (id=%s): %s", title, entry_id, reason)
                    changer.hold(entry, WAITING_FOR_REQUIREMENTS, reason, _refusal_issues(e) or [reason], now)
                    skipped.append(f"'{title}' — {reason}")
                    continue
                logger.info("Published entry '%s' (id=%s)", title, entry_id)
                published.append(title)

        if not due:
            # Nothing to record: this runs every few minutes as a system task (see execute's contract)
            logger.debug("Publish scheduled entries: none due in %s", scope_label)
            return None

        summary = self._summary(published, skipped, waiting, dry_run)
        logger.info("Publish scheduled entries: %s", summary)
        return summary

    @staticmethod
    def _summary(published: list[str], skipped: list[str], waiting: list[str], dry_run: bool) -> str:
        parts = []
        if published:
            label = "would publish" if dry_run else "published"
            parts.append(f"{_entries(len(published))} {label}: {_titles(published)}")
        if skipped:
            count = f"{len(skipped)}" if parts else _entries(len(skipped))
            parts.append(f"{count} skipped (can't publish: {_limited(skipped, '; ')})")
        if waiting:
            count = f"{len(waiting)}" if parts else _entries(len(waiting))
            parts.append(f"{count} waiting for approval: {_titles(waiting)}")
        summary = "; ".join(parts)
        return f"{summary} (dry run)" if dry_run else summary


class UnpublishExpiredEntriesHandler(ScheduledTaskHandler):
    """
    Archive published entries with expire_at <= now, scoped to the task's workspace (every
    workspace for the built-in system task).

    Each entry is archived as a manual status change would archive it (EntryService), so the same
    events fire: entry_updated, entry_unpublished and entry_archived.

    Expiring consumes the date (expire_at is cleared, as publishing clears publish_at), so an entry
    re-published afterwards stays published instead of being archived again on the next run. Only
    this task clears it: a manual archive or unpublish leaves a pending expiry for when the entry
    goes live again.

    Configuration (task_config):
    - dry_run: bool (default: False) - If true, log what would be unpublished
    """

    name = "Unpublish Expired Entries"
    description = "Archive entries whose expire_at time has passed"
    can_run_platform_wide = True

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        dry_run = task.task_config.get("dry_run", False)
        workspace_id = UUID(str(task.group_id)) if task.group_id else None
        scope_label = str(workspace_id) if workspace_id else "all workspaces"

        archived: list[str] = []
        with session_context() as session:
            q = session.query(Entries).filter(
                Entries.expire_at <= datetime.now(UTC),
                Entries.status == "published",
            )
            if workspace_id:
                q = q.filter(Entries.group_id == workspace_id)
            expired = q.all()
            logger.debug("Found %d expired entries in %s (dry_run=%s)", len(expired), scope_label, dry_run)

            changer = _StatusChanger(session, event_bus)
            for entry in expired:
                entry_id, title = entry.id, entry.title
                if dry_run:
                    logger.info("Would unpublish: %s (id=%s, expire_at=%s)", title, entry_id, entry.expire_at)
                else:
                    changer.set_status(entry, "archived", expire_at=None)
                    logger.info("Unpublished expired entry '%s' (id=%s)", title, entry_id)
                archived.append(title)

        if not archived:
            logger.debug("Unpublish expired entries: none expired in %s", scope_label)
            return None

        label = "would unpublish" if dry_run else "archived"
        summary = f"{_entries(len(archived))} {label}: {_titles(archived)}"
        if dry_run:
            summary += " (dry run)"

        logger.info("Unpublish expired entries: %s", summary)
        return summary


class RequestSiteRebuildHandler(ScheduledTaskHandler):
    """
    Request a static site rebuild for the task's workspace (every workspace for a system task).

    Requests are coalesced (marvin.services.site_rebuild): the scheduler dispatches one
    `webhook_triggered` per workspace once requests go quiet, so a burst — a workflow per entry in
    a bulk edit — costs one build.

    Configuration (task_config):
    - reason: str (default: "scheduled") - Reason for the rebuild
    """

    name = "Request Site Rebuild"
    description = "Queue a static site rebuild; one webhook_triggered event is sent once requests go quiet"

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.core.config import get_app_settings
        from marvin.db.models.groups.groups import Groups
        from marvin.services.site_rebuild import rebuild_change, request_rebuild

        reason = task.task_config.get("reason", "scheduled")

        with session_context() as session:
            if task.group_id:
                workspace_ids = [UUID(str(task.group_id))]
            else:
                # Admin system task — rebuild every workspace
                workspace_ids = [row[0] for row in session.query(Groups.id).all()]
            counts = [request_rebuild(session, wid, reason, change=rebuild_change(reason)) for wid in workspace_ids]

        scope = "this workspace" if task.group_id else f"all {len(workspace_ids)} workspaces"
        pending = f", {counts[0]} requests pending" if task.group_id and counts[0] > 1 else ""
        quiet = get_app_settings().SITE_REBUILD_QUIET_SECONDS
        summary = f"Site rebuild queued ({scope}, reason: {reason}{pending}); sent once requests are quiet for {quiet}s"
        logger.info(summary)
        return summary


def dispatch_site_rebuild(
    group_id: UUID,
    reason: str,
    event_bus: EventBusService | None = None,
    changes: list[dict] | None = None,
    request_count: int | None = None,
) -> None:
    """Send the `webhook_triggered` event that the workspace's deploy-hook webhooks listen for.

    It carries what the rebuild covers (`changes`, newest last) so the admin can show what's building;
    a deploy hook ignores the body.
    """
    from marvin.services.site_rebuild import deploy_target_fields

    changes = changes or []
    (event_bus or EventBusService(bg_tasks=None)).dispatch(
        integration_id="scheduled_tasks",
        group_id=group_id,
        event_type=EventTypes.webhook_triggered,
        document_data=EventSiteRebuildData(
            workspace_id=group_id,
            request_count=request_count if request_count is not None else len(changes) or 1,
            changes=[SiteRebuildChange.model_validate(c) for c in changes],
        ),
        message=f"Site rebuild requested: {reason}",
        **deploy_target_fields(group_id),
    )


# Register handlers
TaskHandlerRegistry.register("publish_scheduled_entries", PublishScheduledEntriesHandler)
TaskHandlerRegistry.register("unpublish_expired_entries", UnpublishExpiredEntriesHandler)
TaskHandlerRegistry.register("request_site_rebuild", RequestSiteRebuildHandler)
