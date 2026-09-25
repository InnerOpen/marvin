"""
System scheduled-task seeder.

Seeds platform-wide (group_id=NULL) default scheduled tasks that ship with Marvin,
mirroring the system email-template seeder (marvin.services.email.system_templates).
Idempotent — keyed on task slug — so it is safe to run on every application startup.
"""

from dataclasses import dataclass, field

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

# "daily" expressed as an interval. We intentionally use an `interval` schedule rather
# than `cron`: ScheduledTasksRepository._compute_next_run only populates next_run_at for
# 'interval'/'once' schedules — cron support is not yet wired (croniter isn't a
# dependency), so a cron task would get next_run_at=None and never become due.
_DAILY_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class SystemTaskDefinition:
    """Declarative definition of a default system scheduled task."""

    slug: str
    name: str
    task_type: str
    description: str
    schedule_type: str
    schedule_config: dict
    task_config: dict = field(default_factory=dict)


SYSTEM_SCHEDULED_TASKS: list[SystemTaskDefinition] = [
    SystemTaskDefinition(
        slug="prune_event_logs",
        name="Prune Event Logs",
        task_type="prune_event_logs",
        description=("Delete audit-trail events older than the retention window (EVENT_LOG_RETENTION_DAYS). Admin-only; runs daily."),
        schedule_type="interval",
        schedule_config={"interval_seconds": _DAILY_SECONDS},
    ),
    SystemTaskDefinition(
        slug="prune_ai_executions",
        name="Prune AI Executions",
        task_type="prune_ai_executions",
        description=(
            "Delete AI execution records older than the retention window (per-workspace "
            "logging_config.retention_days, else AI_EXECUTION_RETENTION_DAYS). Admin-only; runs daily."
        ),
        schedule_type="interval",
        schedule_config={"interval_seconds": _DAILY_SECONDS},
    ),
    SystemTaskDefinition(
        slug="prune_scheduled_task_executions",
        name="Prune Scheduled Task Executions",
        task_type="prune_scheduled_task_executions",
        description=(
            "Delete scheduled-task execution records older than the retention window. Admin-only; runs daily. "
            "Without this the table grows without limit — a task on a two-minute interval writes ~720 rows a day."
        ),
        schedule_type="interval",
        schedule_config={"interval_seconds": _DAILY_SECONDS},
        task_config={"retention_days": 30},
    ),
    SystemTaskDefinition(
        slug="resync_smart_collections",
        name="Resync Smart Collections",
        task_type="resync_smart_collections",
        description=(
            "Reconcile smart-collection membership from rules across all workspaces (safety net for the live reaction). Admin-only; runs daily."
        ),
        schedule_type="interval",
        schedule_config={"interval_seconds": _DAILY_SECONDS},
    ),
]


def seed_system_scheduled_tasks(session) -> int:
    """
    Create system-wide (group_id=NULL) default scheduled tasks if they don't exist.

    Idempotent — skips any task whose slug is already present. Returns the number of
    tasks created.
    """
    from marvin.repos.repository_factory import AllRepositories

    repos = AllRepositories(session, group_id=None)

    created = 0
    for defn in SYSTEM_SCHEDULED_TASKS:
        if repos.scheduled_tasks.get_by_slug(defn.slug):
            continue

        repos.scheduled_tasks.create(
            {
                "name": defn.name,
                "slug": defn.slug,
                "description": defn.description,
                "enabled": True,
                "schedule_type": defn.schedule_type,
                "schedule_config": defn.schedule_config,
                "task_type": defn.task_type,
                "task_config": defn.task_config,
            }
        )
        created += 1
        logger.info(f"Seeded system scheduled task: {defn.slug}")

    if created:
        logger.info(f"Scheduled task seeder: created {created} system task(s)")
    else:
        logger.debug("Scheduled task seeder: system tasks already present")

    return created
