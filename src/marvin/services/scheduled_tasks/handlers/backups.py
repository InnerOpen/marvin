"""Run a backup target from Admin → Scheduled Tasks: on a schedule Marvin owns, or with Run Now.

The backup itself runs where it always does — a Job from the target's CronJob, or (no Kubernetes) a child
process (services/backup_runner.py) — and records itself in ``backup_runs``, so Backup health and the
backup alerts treat it like any other run. This handler only starts it.
"""

from marvin.core.root_logger import get_logger
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger(__name__)


class RunBackupTargetHandler(ScheduledTaskHandler):
    """
    Start one backup target's run (admin only).

    Configuration (task_config):
    - target: str (required) - the target's name, one of BACKUP_TARGETS (the chart's backup.targets names)

    An *enabled* task with a cron schedule owns the target's schedule: the run records that schedule, so
    Backup health knows when the next one is due (suspend the target's CronJob then, or both run). A
    disabled task is Run Now only and leaves the CronJob's schedule as the one recorded.
    """

    name = "Run Backup Target"
    description = "Back up the database, config and assets to one backup target (admin only)"
    admin_only = True
    config_schema = {
        "type": "object",
        "required": ["target"],
        "properties": {
            "target": {
                "type": "string",
                "description": "Backup target name (from backup.targets, e.g. r2)",
            },
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: run_backup_target is admin-only and cannot run in a workspace context"

        from marvin.core.config import get_app_settings
        from marvin.services import backup_runner

        settings = get_app_settings()
        if not settings.BACKUP_RUNNER:
            raise ValueError("Backups can't be started from Marvin here: BACKUP_RUNNER is not set (chart: backup.scheduledTasks.enabled)")
        targets = backup_runner.parse_targets(settings.BACKUP_TARGETS)
        name = (task.task_config or {}).get("target")
        if name not in targets:
            known = ", ".join(sorted(targets)) or "none"
            raise ValueError(f"Unknown backup target {name!r} (configured: {known})")

        env = backup_runner.schedule_env(*_owned_schedule(task))
        started = backup_runner.start(settings.BACKUP_RUNNER, name, targets[name], env, cronjob_prefix=settings.BACKUP_CRONJOB_PREFIX)
        if started.already_running:
            return f"Skipped: backup {name} is already running ({started.detail})"
        return f"Started backup {name} ({started.detail}); its result appears in Admin → Backup health"


def _owned_schedule(task: ScheduledTaskModel) -> tuple[str | None, str | None]:
    """(cron expression, time zone) when this task schedules the target, else (None, None)."""
    if not task.enabled or task.schedule_type != "cron":
        return None, None
    config = task.schedule_config or {}
    return config.get("cron_expression"), config.get("timezone")


class CreateWorkspaceBundlesHandler(ScheduledTaskHandler):
    """
    Write every workspace's backup bundle (the Backups feature's zip: its content, settings and asset files,
    secrets encrypted under the workspace's backup key) into BACKUP_DIR, on a schedule.

    These are per-workspace restore points: import one into a workspace from Admin → Backups. The backup
    targets copy them off-site (`bundles/<workspace>/`, backup_engine), so the backend never needs a target's
    credentials. Locally only the newest `keep` scheduled bundles per workspace stay; a bundle someone made by
    hand (no "scheduled" in its name) is never removed here.

    Configuration (task_config):
    - keep: int (default: 2) - scheduled bundles kept on the data volume per workspace (>= 1)
    """

    name = "Workspace Backup Bundles"
    description = "Write a backup bundle of every workspace for the backup targets to copy off-site (admin only)"
    admin_only = True
    config_schema = {
        "type": "object",
        "properties": {
            "keep": {"type": "integer", "default": 2, "minimum": 1, "description": "Scheduled bundles kept locally per workspace"},
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: create_workspace_bundles is admin-only and cannot run in a workspace context"

        from marvin.core.config import get_app_dirs
        from marvin.db.db_setup import session_context
        from marvin.db.models.groups import Groups
        from marvin.repos.all_repositories import get_repositories
        from marvin.repos.seed.workspace_exporter import WorkspaceExporter

        keep = max(int((task.task_config or {}).get("keep", 2)), 1)
        backup_dir = get_app_dirs().BACKUP_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
        from marvin.services.storage.workspace_backups import announce, has_own_backups, save_backup

        written, total_bytes, removed, failed, own_saved = 0, 0, 0, [], 0
        with session_context() as session:
            workspaces = [(g.id, g.slug) for g in session.query(Groups).order_by(Groups.slug).all()]
            for group_id, slug in workspaces:
                try:
                    zip_path = WorkspaceExporter(get_repositories(session, group_id=group_id)).export_workspace_bundle(
                        temp_dir=backup_dir, label=SCHEDULED_LABEL
                    )
                except Exception as e:  # noqa: BLE001 — one workspace failing must not cost the others their bundle
                    session.rollback()
                    logger.warning("Workspace bundle %s failed: %s", slug, e)
                    failed.append(slug)
                    continue
                written += 1
                total_bytes += zip_path.stat().st_size
                if has_own_backups(session, group_id):  # its own private backup bucket too (BYO storage)
                    try:
                        announce(event_bus, group_id, saved=save_backup(session, group_id, zip_path))
                        own_saved += 1
                    except Exception as e:  # noqa: BLE001 — reported for this workspace; the others go on
                        session.rollback()
                        logger.warning("Workspace %s: own backup bucket failed: %s", slug, e)
                        announce(event_bus, group_id, error=str(e))
                        failed.append(f"{slug} (own bucket)")
                removed += _prune_scheduled(backup_dir, slug, keep)

        summary = f"Bundled {written} workspace(s), {total_bytes / 1024**2:.1f} MB; removed {removed} older scheduled bundle(s)"
        if own_saved:
            summary += f"; {own_saved} saved to the workspace's own backup bucket"
        if failed:
            # Raise so the run is recorded as failed (and alerts), after the others were written.
            raise RuntimeError(f"{summary}; failed: {', '.join(failed)}")
        logger.info("Workspace bundles: %s", summary)
        return summary


SCHEDULED_LABEL = "scheduled"


def _prune_scheduled(backup_dir, slug: str, keep: int) -> int:
    """Remove all but the newest `keep` scheduled bundles of one workspace; hand-made bundles are left alone."""
    # "<slug>-backup-" anchors the workspace: another slug that merely starts with this one ("acme-co") differs there.
    mine = sorted(backup_dir.glob(f"{slug}-backup-*-{SCHEDULED_LABEL}-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    stale = mine[keep:]
    for path in stale:
        path.unlink(missing_ok=True)
    return len(stale)


TaskHandlerRegistry.register("run_backup_target", RunBackupTargetHandler)
TaskHandlerRegistry.register("create_workspace_bundles", CreateWorkspaceBundlesHandler)
