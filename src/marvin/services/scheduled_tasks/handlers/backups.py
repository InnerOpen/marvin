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


TaskHandlerRegistry.register("run_backup_target", RunBackupTargetHandler)
