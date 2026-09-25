"""
Maintenance task handlers for cleanup and housekeeping.

These handlers perform routine maintenance operations like cleaning up temp files,
pruning old data, and verifying system integrity.
"""

from datetime import UTC, datetime, timedelta

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.repos.repository_factory import AllRepositories
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger(__name__)


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024**2:.1f} MB"


class CleanupTempFilesHandler(ScheduledTaskHandler):
    """
    Remove old files from the system temporary upload directory.

    Admin-only: operates on the shared system temp dir, not workspace data.
    Workspace-scoped tasks are rejected.

    Configuration (task_config):
    - age_hours: int (default: 24) - Files older than this are deleted
    - dry_run: bool (default: False) - If true, log what would be deleted
    """

    name = "Cleanup Temporary Files"
    description = "Remove old files from temporary upload storage (admin only)"
    admin_only = True
    config_schema = {
        "type": "object",
        "properties": {
            "age_hours": {
                "type": "integer",
                "default": 24,
                "description": "Files older than this many hours will be deleted",
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "If true, log what would be deleted without actually deleting",
            },
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: cleanup_temp_files is admin-only and cannot run in a workspace context"

        config = task.task_config
        age_hours = config.get("age_hours", 24)
        dry_run = config.get("dry_run", False)

        from marvin.core.config import get_app_dirs

        temp_dir = get_app_dirs().TEMP_DIR

        if not temp_dir.exists():
            msg = f"Temp directory does not exist: {temp_dir}"
            logger.info(msg)
            return msg

        cutoff = datetime.now(UTC) - timedelta(hours=age_hours)
        deleted_count = 0
        deleted_bytes = 0

        for file_path in temp_dir.rglob("*"):
            if not file_path.is_file():
                continue

            mtime = file_path.stat().st_mtime
            file_mtime = datetime.fromtimestamp(mtime, tz=UTC)
            if file_mtime < cutoff:
                file_size = file_path.stat().st_size
                if dry_run:
                    logger.info("Would delete: %s (%s)", file_path, _fmt_bytes(file_size))
                else:
                    file_path.unlink()
                    logger.debug("Deleted: %s (%s)", file_path, _fmt_bytes(file_size))
                deleted_count += 1
                deleted_bytes += file_size

        label = "dry run — would delete" if dry_run else "deleted"
        summary = f"{deleted_count} file{'s' if deleted_count != 1 else ''} {label}, {_fmt_bytes(deleted_bytes)} freed"
        logger.info("Temp file cleanup: %s", summary)
        return summary


class PruneExpiredSessionsHandler(ScheduledTaskHandler):
    """
    Remove expired user sessions from the database.

    Note: Marvin uses JWT tokens — no server-side session storage to prune.
    """

    name = "Prune Expired Sessions"
    description = "Remove expired user sessions (no-op: Marvin uses stateless JWTs)"

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        msg = "No-op: Marvin uses stateless JWT tokens — no session records to prune"
        logger.info(msg)
        return msg


class PruneExpiredInvitationsHandler(ScheduledTaskHandler):
    """
    Remove expired workspace invitations scoped to the task's workspace.

    Configuration (task_config):
    - age_days: int (default: 30) - Invitations older than this are deleted
    """

    name = "Prune Expired Invitations"
    description = "Remove workspace invitations older than age_days"
    config_schema = {
        "type": "object",
        "properties": {
            "age_days": {
                "type": "integer",
                "default": 30,
                "description": "Delete invitations older than this many days",
            },
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.db.models.groups.invite_tokens import GroupInviteToken

        config = task.task_config
        age_days = config.get("age_days", 30)
        cutoff = datetime.now(UTC) - timedelta(days=age_days)

        with session_context() as session:
            q = session.query(GroupInviteToken).filter(GroupInviteToken.created_at <= cutoff)
            if task.group_id:
                q = q.filter(GroupInviteToken.group_id == task.group_id)

            expired = q.all()
            count = len(expired)
            for inv in expired:
                session.delete(inv)
            session.commit()

        scope = "all workspaces" if not task.group_id else "this workspace"
        summary = f"{count} expired invitation{'s' if count != 1 else ''} deleted (older than {age_days} days, scope: {scope})"
        logger.info("Invitation cleanup: %s", summary)
        return summary


class RemoveOrphanedAssetsHandler(ScheduledTaskHandler):
    """
    Find and optionally remove assets not linked to any entries,
    scoped to the task's workspace.

    Configuration (task_config):
    - age_days: int (default: 30) - Only consider assets older than this
    - auto_delete: bool (default: False) - If true, delete orphans; if false, just report
    """

    name = "Remove Orphaned Assets"
    description = "Find (and optionally delete) assets not linked to any entries in this workspace"
    config_schema = {
        "type": "object",
        "properties": {
            "age_days": {
                "type": "integer",
                "default": 30,
                "description": "Only consider assets older than this many days",
            },
            "auto_delete": {
                "type": "boolean",
                "default": False,
                "description": "If true, delete orphans; if false, just report",
            },
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.db.models.platform import Assets, EntryAssets

        config = task.task_config
        age_days = config.get("age_days", 30)
        auto_delete = config.get("auto_delete", False)

        cutoff = datetime.now(UTC) - timedelta(days=age_days)

        with session_context() as session:
            asset_q = session.query(Assets).filter(Assets.created_at <= cutoff)
            if task.group_id:
                asset_q = asset_q.filter(Assets.group_id == task.group_id)

            all_assets = asset_q.all()

            # Scope linked-ids query to the same set of assets
            link_q = session.query(EntryAssets.asset_id).join(Assets, Assets.id == EntryAssets.asset_id)
            if task.group_id:
                link_q = link_q.filter(Assets.group_id == task.group_id)
            linked_ids = {row[0] for row in link_q.all()}

            orphans = [a for a in all_assets if a.id not in linked_ids]
            count = len(orphans)

            if auto_delete:
                for asset in orphans:
                    session.delete(asset)
                session.commit()
                label = "deleted"
            else:
                label = "found (auto_delete=false, not removed)"

        scope = "this workspace" if task.group_id else "all workspaces"
        summary = f"{count} orphaned asset{'s' if count != 1 else ''} {label} (older than {age_days} days, scope: {scope})"
        logger.info("Orphaned asset scan: %s", summary)
        return summary


class PruneEventLogsHandler(ScheduledTaskHandler):
    """
    Delete old rows from the event_log audit trail (platform-wide, all workspaces).

    Admin-only: operates across the whole event log, not a single workspace.

    Configuration (task_config):
    - retention_days: int - Delete events older than this many days. Defaults to the
      EVENT_LOG_RETENTION_DAYS app setting. A value <= 0 disables pruning (keep forever).
    """

    name = "Prune Event Logs"
    description = "Delete audit-trail events older than the retention window (admin only)"
    admin_only = True
    config_schema = {
        "type": "object",
        "properties": {
            "retention_days": {
                "type": "integer",
                "description": "Delete events older than this many days (<=0 disables). Defaults to the EVENT_LOG_RETENTION_DAYS setting.",
            },
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: prune_event_logs is admin-only and cannot run in a workspace context"

        from marvin.core.config import get_app_settings

        default_days = getattr(get_app_settings(), "EVENT_LOG_RETENTION_DAYS", 90)
        retention_days = task.task_config.get("retention_days", default_days)
        if not retention_days or retention_days <= 0:
            msg = "Skipped: event log retention disabled (retention_days <= 0)"
            logger.info(msg)
            return msg

        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        with session_context() as session:
            repos = AllRepositories(session, group_id=None)
            deleted = repos.event_log.prune_older_than(cutoff)

        summary = f"Pruned {deleted} event log row{'s' if deleted != 1 else ''} older than {retention_days} days"
        logger.info("Event log prune: %s", summary)
        return summary


class PruneAIExecutionsHandler(ScheduledTaskHandler):
    """
    Delete old rows from the ai_executions log (platform-wide, all workspaces).

    Admin-only. Each workspace's retention comes from its `logging_config.retention_days`
    when set; workspaces without one fall back to the AI_EXECUTION_RETENTION_DAYS app
    setting (overridable via task_config.retention_days). A retention <= 0 disables pruning
    for that scope (keep forever).
    """

    name = "Prune AI Executions"
    description = "Delete AI execution records older than the retention window (admin only)"
    admin_only = True
    config_schema = {
        "type": "object",
        "properties": {
            "retention_days": {
                "type": "integer",
                "description": "Fallback retention for workspaces without a logging_config "
                "value (<=0 disables). Defaults to the AI_EXECUTION_RETENTION_DAYS setting.",
            },
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: prune_ai_executions is admin-only and cannot run in a workspace context"

        from marvin.core.config import get_app_settings
        from marvin.db.models.groups.ai_executions import AIExecutionModel
        from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

        default_days = task.task_config.get("retention_days", getattr(get_app_settings(), "AI_EXECUTION_RETENTION_DAYS", 90))
        now = datetime.now(UTC)

        def _delete_older(session, days: int, group_ids=None, exclude_group_ids=None) -> int:
            if not days or days <= 0:
                return 0
            cutoff = now - timedelta(days=days)
            q = session.query(AIExecutionModel).filter(AIExecutionModel.created_at < cutoff)
            if group_ids is not None:
                q = q.filter(AIExecutionModel.group_id.in_(group_ids))
            if exclude_group_ids:
                q = q.filter(AIExecutionModel.group_id.notin_(exclude_group_ids))
            return q.delete(synchronize_session=False)

        total = 0
        with session_context() as session:
            # Per-workspace retention overrides from logging_config.retention_days.
            overrides: dict = {}
            for s in session.query(WorkspaceAISettingsModel).all():
                rd = (s.logging_config or {}).get("retention_days")
                if rd is not None:
                    overrides[s.group_id] = rd
            for gid, days in overrides.items():
                total += _delete_older(session, days, group_ids=[gid])
            # Everyone else uses the default retention.
            total += _delete_older(session, default_days, exclude_group_ids=list(overrides.keys()) or None)
            session.commit()

        summary = f"Pruned {total} AI execution row{'s' if total != 1 else ''} past retention"
        logger.info("AI execution prune: %s", summary)
        return summary


class PruneScheduledTaskExecutionsHandler(ScheduledTaskHandler):
    """
    Delete old rows from scheduled_task_execution_log (platform-wide, all workspaces).

    Admin-only. This table had no pruning at all while event logs and AI executions did, so it grew
    without limit — a task on a two-minute interval writes ~720 rows a day on its own.

    Configuration (task_config):
    - retention_days: int (default: 30) - Delete executions older than this. A value <= 0 disables.
    """

    name = "Prune Scheduled Task Executions"
    description = "Delete scheduled-task execution records older than the retention window (admin only)"
    admin_only = True
    config_schema = {
        "type": "object",
        "properties": {
            "retention_days": {
                "type": "integer",
                "default": 30,
                "description": "Delete execution records older than this many days (<=0 disables).",
            },
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: prune_scheduled_task_executions is admin-only and cannot run in a workspace context"

        from marvin.db.models.platform.scheduled_tasks import ScheduledTaskExecutionLogModel

        retention_days = task.task_config.get("retention_days", 30)
        if not retention_days or retention_days <= 0:
            return "Skipped: execution log retention disabled (retention_days <= 0)"

        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        with session_context() as session:
            deleted = (
                session.query(ScheduledTaskExecutionLogModel)
                .filter(ScheduledTaskExecutionLogModel.executed_at < cutoff)
                .delete(synchronize_session=False)
            )
            session.commit()

        if not deleted:
            return None  # nothing to say; do not add a row to the log we are pruning
        summary = f"Pruned {deleted} execution record{'s' if deleted != 1 else ''} older than {retention_days} days"
        logger.info("Execution log prune: %s", summary)
        return summary


class ResyncSmartCollectionsHandler(ScheduledTaskHandler):
    """
    Reconcile smart-collection membership across all workspaces (platform-wide).

    Membership is normally kept live by the SmartCollectionReactionListener on entry changes;
    this is a safety net that re-materializes every smart collection from its rules, catching
    drift from missed events, downtime, or bulk imports. Admin-only.
    """

    name = "Resync Smart Collections"
    description = "Reconcile smart-collection membership from rules across all workspaces (admin only)"
    admin_only = True

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: resync_smart_collections is admin-only and cannot run in a workspace context"

        from marvin.db.models.platform.collections import Collections
        from marvin.services.collections.smart_collections import sync_collection

        collections = 0
        changed = 0
        with session_context() as session:
            for collection in session.query(Collections).filter_by(is_smart=True).all():
                collections += 1
                changed += sync_collection(session, collection.group_id, collection)
            session.commit()

        summary = f"Reconciled {collections} smart collection(s), {changed} membership change(s)"
        logger.info("Smart collection resync: %s", summary)
        return summary


# Register handlers
TaskHandlerRegistry.register("cleanup_temp_files", CleanupTempFilesHandler)
TaskHandlerRegistry.register("prune_expired_sessions", PruneExpiredSessionsHandler)
TaskHandlerRegistry.register("prune_expired_invitations", PruneExpiredInvitationsHandler)
TaskHandlerRegistry.register("remove_orphaned_assets", RemoveOrphanedAssetsHandler)
TaskHandlerRegistry.register("prune_event_logs", PruneEventLogsHandler)
TaskHandlerRegistry.register("prune_ai_executions", PruneAIExecutionsHandler)
TaskHandlerRegistry.register("prune_scheduled_task_executions", PruneScheduledTaskExecutionsHandler)
TaskHandlerRegistry.register("resync_smart_collections", ResyncSmartCollectionsHandler)
