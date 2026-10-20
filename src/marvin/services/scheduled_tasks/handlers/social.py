"""
Social engagement task handlers.

``social_engagement`` — the engine: read new comments on every connected network (for the Social inbox and the
``social_comment_received`` event workflows can start on) and, on each network whose auto-reply is rehearsal or on, answer under
the published rules. A thin wrapper — the engine, its approval path and its rehearsal live in
services/integrations/social_engagement.py. Marvin makes and switches this task on itself while a network reads comments
(services/integrations/social_setup.py); it is not something to set up.

Deliberately NOT on AUTOMATION_ALLOWED_HANDLERS: it sends replies, so it runs only as a scheduled task, never from a workflow.

``reconcile_social_engagement`` — a platform maintenance task (admin only, hourly): makes each workspace's plumbing match its
networks (the rule type, the engine task created and enabled, or disabled when no network reads comments).
"""

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger(__name__)


class SocialEngagementHandler(ScheduledTaskHandler):
    """
    Read new comments on each connected network and reply under the published `social-auto-reply` rules, on the networks
    whose auto-reply is on (or rehearsing).

    Configuration (task_config):
    - max_replies: int — at most this many replies per run (default 20)
    - max_age_days: int — ignore comments older than this (default 7, at most 90)
    - limit: int — items read per network per run (default 50)

    Whether a network replies is its own setting (off | rehearsal | on), not the task's. An old `rehearsal` key is mapped onto
    the networks once, then removed.
    """

    name = "Social Engagement"
    description = (
        "Read new comments on every connected social network (the Social inbox, and workflows on social_comment_received) "
        "and answer under published auto-reply rules on the networks whose auto-reply is on"
    )
    config_schema = {
        "type": "object",
        "properties": {
            "max_replies": {"type": "integer", "description": "Most replies per run (default 20)"},
            "max_age_days": {"type": "integer", "description": "Ignore comments older than this many days (default 7, at most 90)"},
            "limit": {"type": "integer", "description": "Comments read per network per run (default 50)"},
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if not task.group_id:
            return "Skipped: social engagement needs a workspace (integrations are per-workspace)"

        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        if not INTEGRATIONS_AVAILABLE:
            return "Skipped: integrations SDK not installed"
        from marvin.services.integrations.social_engagement import Settings, run_engagement
        from marvin.services.integrations.social_setup import map_legacy_rehearsal

        with session_context() as session:
            stored = session.get(ScheduledTaskModel, task.id)
            if stored is not None and map_legacy_rehearsal(session, task.group_id, stored):
                logger.info("social engagement: mapped the task's old rehearsal setting onto its networks")
            report = run_engagement(session, task.group_id, Settings.from_config(task.task_config), event_bus=event_bus)
        summary = report.summary()
        # Quiet on a routine nothing-to-answer run (every 5 minutes): None means "not worth a row".
        if not report.worth_logging:
            logger.debug(summary)
            return None
        logger.info(summary)
        return summary


class ReconcileSocialEngagementHandler(ScheduledTaskHandler):
    """Make every workspace's Social plumbing match its networks: the rule type once a network offers a social capability, the
    engine task created and enabled while one reads comments, disabled when none does. Admin-only; runs hourly."""

    name = "Reconcile Social Engagement"
    description = "Create and enable (or disable) each workspace's Social engagement task to match its connected networks (admin only)"
    admin_only = True
    config_schema = {"type": "object", "properties": {}}

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: reconcile_social_engagement is admin-only and cannot run in a workspace context"
        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        if not INTEGRATIONS_AVAILABLE:
            return "Skipped: integrations SDK not installed"
        from marvin.services.integrations.social_setup import reconcile_all

        with session_context() as session:
            done = reconcile_all(session)
        if not (done["created"] or done["enabled"] or done["disabled"] or done["failed"]):
            return None
        summary = f"Social engagement: created {done['created']}, enabled {done['enabled']}, disabled {done['disabled']}, failed {done['failed']}"
        logger.info(summary)
        return summary


TaskHandlerRegistry.register("social_engagement", SocialEngagementHandler)
TaskHandlerRegistry.register("reconcile_social_engagement", ReconcileSocialEngagementHandler)
