"""
Media enrichment scheduled task handler.

Runs the recipe's ``derive`` media steps (grade/crop + ``enrichment.media``) on one entry via
``MediaEnrichmentService.run_for_entry``. Exposed as a task handler so media enrichment fires on
ANY authoring path — a user automation ("entry_published & entry_type==project → media_enrich")
runs it after backend/publish edits, not just AI compose.
"""

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.repos.repository_factory import AllRepositories
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger(__name__)


class MediaEnrichHandler(ScheduledTaskHandler):
    """
    Derive media variants (grade/crop) for one entry per its type's recipe.

    Configuration (task_config):
    - entry_id: str (required) — the entry to enrich. An automation interpolates
      ``{"entry_id": "$event.entry_id"}`` into this.

    Best-effort: a missing/unknown entry is a no-op. Provider/model are omitted (local grade/crop
    is the main use); vision ``crop:subject`` skips cleanly without a vision backend.
    """

    name = "Enrich Entry Media"
    description = "Run the entry type's recipe media derivations (grade/crop) on one entry"
    config_schema = {
        "type": "object",
        "properties": {"entry_id": {"type": "string"}},
        "required": ["entry_id"],
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.services.ai.media.enrichment import MediaEnrichmentService

        config = task.task_config or {}
        entry_id = config.get("entry_id")
        if not entry_id:
            logger.warning("media_enrich: no entry_id in task_config; skipping")
            return "media_enrich: no entry_id"

        group_id = task.group_id
        with session_context() as session:
            repos = AllRepositories(session, group_id=group_id)
            summaries = MediaEnrichmentService(session, repos, group_id).run_for_entry(entry_id)

        summary = f"media_enrich: {len(summaries)} derivative(s)"
        logger.info("%s (entry=%s)", summary, entry_id)
        return summary


TaskHandlerRegistry.register("media_enrich", MediaEnrichHandler)
