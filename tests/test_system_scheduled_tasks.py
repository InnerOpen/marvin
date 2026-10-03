"""The platform-wide scheduled tasks Marvin ships with itself.

These are seeded at startup (`marvin.app`), so a definition that does not line up with a registered
handler would be created once and then fail on every run, for every deployment.
"""

from marvin.services.scheduled_tasks import TaskHandlerRegistry
from marvin.services.scheduled_tasks.system_tasks import SYSTEM_SCHEDULED_TASKS


def test_every_system_task_has_a_handler_registered():
    missing = [d.slug for d in SYSTEM_SCHEDULED_TASKS if not TaskHandlerRegistry.is_registered(d.task_type)]
    assert missing == [], f"system tasks declared against unregistered handlers: {missing}"


def test_system_tasks_use_handlers_that_run_platform_wide():
    # They run with group_id=NULL across every workspace; a workspace-scoped handler would refuse.
    def platform_wide(task_type):
        handler = TaskHandlerRegistry.get_handler(task_type)
        return handler.admin_only or handler.can_run_platform_wide

    scoped = [d.slug for d in SYSTEM_SCHEDULED_TASKS if not platform_wide(d.task_type)]
    assert scoped == [], f"system tasks using workspace-only handlers: {scoped}"


def test_schedules_can_actually_become_due():
    # _compute_next_run only fills next_run_at for interval/once — a cron task would sit at None
    # and never run. Until croniter is a dependency, system tasks must not use cron.
    assert {d.schedule_type for d in SYSTEM_SCHEDULED_TASKS} <= {"interval", "once"}


def test_slugs_are_unique():
    slugs = [d.slug for d in SYSTEM_SCHEDULED_TASKS]
    assert len(slugs) == len(set(slugs))


def test_the_execution_log_is_pruned():
    """It was the one log table with no pruning while event logs and AI executions both had it."""
    assert any(d.task_type == "prune_scheduled_task_executions" for d in SYSTEM_SCHEDULED_TASKS)


def test_scheduled_publishing_runs_out_of_the_box():
    """Scheduled Publish / Expiration did nothing unless a workspace created its own task."""
    shipped = {d.task_type: d.schedule_config.get("interval_seconds") for d in SYSTEM_SCHEDULED_TASKS}
    assert (shipped.get("publish_scheduled_entries"), shipped.get("unpublish_expired_entries")) == (300, 300)
