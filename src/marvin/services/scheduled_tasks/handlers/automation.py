"""Scheduled-task handler that runs a Flavor B automation on a schedule.

Backs the `trigger.type="schedule"` automation trigger: the automations controller upserts a
`run_automation` scheduled task whose `task_config` names the automation; when the Scheduler fires
it, this handler loads that automation and runs its action pipeline (skipping the trigger/condition
gates, like the Manual Run).
"""

from marvin.core.root_logger import get_logger
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger("scheduled_tasks")


class RunAutomationHandler(ScheduledTaskHandler):
    """Run the workspace automation named in `task_config.automation_id`."""

    name = "Run Automation"
    description = "Run a workspace automation on a schedule (the schedule trigger for Workflows)."
    config_schema = {
        "type": "object",
        "properties": {"automation_id": {"type": "string"}},
        "required": ["automation_id"],
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.db.db_setup import session_context
        from marvin.db.models.groups.automations import WorkspaceAutomationModel
        from marvin.services.automation.engine import run_automation_now
        from marvin.services.automation.recorder import ExecutionRecorder

        automation_id = (task.task_config or {}).get("automation_id")
        if not automation_id:
            return "no automation_id in task config"

        with session_context() as session:
            automation = session.get(WorkspaceAutomationModel, automation_id)
            if not automation or (task.group_id and automation.group_id != task.group_id):
                return f"automation {automation_id} not found"
            if not automation.enabled:
                return f"automation '{automation.slug}' is disabled — skipped"
            res = run_automation_now(
                session,
                automation.group_id,
                automation,
                user_id=None,
                logger=logger,
                recorder=ExecutionRecorder(session, automation.group_id),
                trigger_kind="schedule",
            )

        summary = f"ran automation '{automation.slug}' (ok={res.get('ok')})"
        logger.info("Scheduled automation: %s", summary)
        return summary


TaskHandlerRegistry.register("run_automation", RunAutomationHandler)
