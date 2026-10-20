"""
Social engagement task handler: answer comments on every connected network under the workspace's published rules, and
announce each new comment, reply or mention as a ``social_comment_received`` event workflows can start on.

A thin wrapper — the engine, its approval path and its rehearsal live in services/integrations/social_engagement.py.
Deliberately NOT on AUTOMATION_ALLOWED_HANDLERS: it sends replies, so it runs only as a scheduled task an admin created
(the core "Social auto-reply" blueprint makes one, disabled and in rehearsal), never from a workflow.
"""

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger(__name__)


class SocialEngagementHandler(ScheduledTaskHandler):
    """
    Read new comments on each connected network and reply under the published `social-auto-reply` rules.

    Configuration (task_config):
    - rehearsal: bool — default true: the plugin is asked what it would send (`dry_run`) and the log says so; send for real
      only when this is explicitly false
    - max_replies: int — at most this many replies per run (default 20)
    - max_age_days: int — ignore comments older than this (default 7)
    - limit: int — items read per network per run (default 50)
    - announce: bool — default true: send `social_comment_received` for each new item, whether or not rehearsal is on and
      whether or not any rule exists (set false for a replies-only engine)
    """

    name = "Social Engagement"
    description = (
        "Read new comments on every connected social network: reply under published auto-reply rules (rehearsal by default) "
        "and start workflows on social_comment_received"
    )
    config_schema = {
        "type": "object",
        "properties": {
            "rehearsal": {"type": "boolean", "description": "Log what would be sent without sending (default true)"},
            "max_replies": {"type": "integer", "description": "Most replies per run (default 20)"},
            "max_age_days": {"type": "integer", "description": "Ignore comments older than this many days (default 7)"},
            "limit": {"type": "integer", "description": "Comments read per network per run (default 50)"},
            "announce": {"type": "boolean", "description": "Announce each new comment as a social_comment_received event (default true)"},
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if not task.group_id:
            return "Skipped: social engagement needs a workspace (integrations are per-workspace)"

        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        if not INTEGRATIONS_AVAILABLE:
            return "Skipped: integrations SDK not installed"
        from marvin.services.integrations.social_engagement import Settings, run_engagement

        with session_context() as session:
            report = run_engagement(session, task.group_id, Settings.from_config(task.task_config), event_bus=event_bus)
        summary = report.summary()
        # Quiet on a routine nothing-to-answer run (every 5 minutes): None means "not worth a row".
        if not report.worth_logging:
            logger.debug(summary)
            return None
        logger.info(summary)
        return summary


TaskHandlerRegistry.register("social_engagement", SocialEngagementHandler)
