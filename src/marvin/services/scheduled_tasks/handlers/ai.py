"""
AI scheduled task handlers.

Rebuild semantic-search (RAG) embeddings on a schedule so answers stay fresh
without a manual reindex. Complements auto-embed-on-publish (event-driven, TBD).
"""

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger(__name__)


class ReindexEmbeddingsHandler(ScheduledTaskHandler):
    """
    Rebuild RAG embeddings for the task's workspace, or for every workspace when
    run as a system task (no group_id).

    Skips workspaces where AI is disabled or whose provider has no embeddings.
    Emits ai_embeddings_reindexed per workspace so notifications/webhooks fire.
    """

    name = "Reindex AI Embeddings"
    sends = ("ai_embeddings_reindexed",)
    description = "Rebuild RAG embeddings for this workspace (or all workspaces for a system task)"
    config_schema = {"type": "object", "properties": {}}

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        from marvin.db.models.groups.groups import Groups
        from marvin.services.ai.embeddings import embedder_for, reindex_workspace
        from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider

        done = 0
        total_entities = total_chunks = total_failed = 0
        with session_context() as session:
            if task.group_id:
                groups = session.query(Groups).filter(Groups.id == task.group_id).all()
            else:
                groups = session.query(Groups).all()

            for g in groups:
                # Marvin's built-in embedding model needs no AI provider: a workspace with AI off is indexed too.
                try:
                    provider = get_workspace_ai_provider(session, g.id)
                except AIDisabledError:
                    provider = None
                except Exception as ex:
                    logger.warning("reindex: provider error for workspace %s: %s", g.id, ex)
                    provider = None
                embedder, model = embedder_for(provider)
                if not model:
                    continue

                result = reindex_workspace(session, g.id, embedder, model)
                total_entities += result.entities
                total_chunks += result.chunks
                total_failed += result.failed
                done += 1
                from marvin.services.ai.reindex_jobs import emit

                emit(g.id, model, result, source="ai_scheduled")

        scope = "this workspace" if task.group_id else "all workspaces"
        summary = f"Reindexed {done} workspace(s) ({scope}): {total_entities} items, {total_chunks} chunks"
        if total_failed:
            summary += f", {total_failed} failed (see the ai_embeddings_reindexed events)"
        logger.info("AI embeddings reindex: %s", summary)
        return summary


class RefreshAIPriceFeedHandler(ScheduledTaskHandler):
    """
    Fetch the AI price feed (services/ai/price_feed.py) — the last source a model's price can come from, after
    an admin's override and the provider's own table. Admin-only. A failed fetch keeps the last good prices and
    fails the run, so the scheduled-task failure alerts fire.
    """

    name = "Refresh AI Price Feed"
    description = "Fetch the AI price list (LiteLLM format, URL set in Admin → AI Pricing) (admin only)"
    admin_only = True

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if task.group_id:
            return "Skipped: refresh_ai_price_feed is admin-only and cannot run in a workspace context"
        from marvin.services.ai import price_feed

        with session_context() as session:
            if not price_feed.effective_url(session):
                return None  # switched off: nothing to do, nothing to log
            state = price_feed.refresh(session)  # raises FeedError: the run fails, the last prices stay
        summary = f"Priced {state['models']} models from {state['fetched_from']}"
        logger.info("AI price feed: %s", summary)
        return summary


TaskHandlerRegistry.register("ai_reindex_embeddings", ReindexEmbeddingsHandler)
TaskHandlerRegistry.register("refresh_ai_price_feed", RefreshAIPriceFeedHandler)
