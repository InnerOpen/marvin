"""Run a workspace's search reindex in the background, one at a time per workspace.

Embedding a whole workspace takes longer than a browser request may last behind the Cloudflare tunnel
(~100 s), so the Reindex button starts a run here and returns; the run reports through the
`ai_embeddings_reindexed` event (activity toast, event log) and `status()` for the settings card.
A second click while a run is going is refused rather than embedding everything twice.

In-process state: a restart drops the progress view, never the embeddings already written.
"""

import threading
from datetime import UTC, datetime

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_running: dict[str, dict] = {}


def status(group_id) -> dict | None:
    """The run in progress for this workspace ({started_at, done, total}), or None."""
    with _lock:
        state = _running.get(str(group_id))
        return dict(state) if state else None


def start(group_id, user_id=None, *, force: bool = False) -> bool:
    """Start a background reindex. False when one is already running for this workspace."""
    key = str(group_id)
    with _lock:
        if key in _running:
            return False
        _running[key] = {"started_at": datetime.now(UTC).isoformat(), "done": 0, "total": 0}
    threading.Thread(target=_run, args=(group_id, user_id, force), name=f"reindex-{key[:8]}", daemon=True).start()
    return True


def _progress(key: str):
    def update(done: int, total: int) -> None:
        with _lock:
            if key in _running:
                _running[key].update(done=done, total=total)

    return update


def _run(group_id, user_id, force: bool) -> None:
    from marvin.db.db_setup import session_context
    from marvin.services.ai.embeddings import ReindexResult, default_embedding_model, reindex_workspace
    from marvin.services.ai.factory import get_workspace_ai_provider

    key = str(group_id)
    model, result = None, ReindexResult()
    try:
        with session_context() as session:
            provider = get_workspace_ai_provider(session, group_id)
            model = default_embedding_model(provider.provider_type)
            result = reindex_workspace(session, group_id, provider, model, force=force, progress=_progress(key))
    except Exception as e:  # noqa: BLE001 — reported through the event, never lost
        logger.error("reindex for %s failed: %s", group_id, e, exc_info=True)
        result.failed += 1
        result.errors.append(f"{type(e).__name__}: {str(e)[:300]}")
    finally:
        with _lock:
            _running.pop(key, None)
    emit(group_id, model or "unknown", result, user_id=user_id, source="ai_operations")


def emit(group_id, model: str, result, *, user_id=None, source: str = "ai_operations") -> None:
    """Dispatch ai_embeddings_reindexed with the run's counts and first error (the toast's detail)."""
    from marvin.db.db_setup import session_context
    from marvin.db.models.groups.groups import Groups
    from marvin.services.event_bus_service.event_bus_service import EventBusService
    from marvin.services.event_bus_service.event_types import EventAIEmbeddingsData, EventTypes

    try:
        with session_context() as session:
            group = session.get(Groups, group_id)
            name = group.name if group else None
        EventBusService(bg_tasks=None).dispatch(
            integration_id=source,
            group_id=group_id,
            event_type=EventTypes.ai_embeddings_reindexed,
            document_data=EventAIEmbeddingsData(
                model_id=model,
                entities_indexed=result.entities,
                chunks_indexed=result.chunks,
                skipped=result.skipped,
                failed=result.failed,
                error=result.errors[0] if result.errors else None,
                workspace_id=group_id,
                workspace_name=name,
            ),
            message=result.summary,
            user_id=user_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("failed to dispatch ai_embeddings_reindexed for %s: %s", group_id, e, exc_info=True)
