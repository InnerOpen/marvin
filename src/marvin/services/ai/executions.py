"""Small helpers over AI execution rows shared by the controller, the tools and the authoring service."""

from __future__ import annotations

PARENT_KEY = "parent_execution_id"


def parent_meta(parent_execution_id: str | None) -> dict | None:
    """`metadata_json` for a row spawned by an agent run — None when there is no parent (a direct call)."""
    return {PARENT_KEY: str(parent_execution_id)} if parent_execution_id else None


def link_child_execution(session, execution_id, parent_execution_id: str | None) -> None:
    """Stamp `parent_execution_id` on an existing row (an AI operation the agent loop ran). No-op without a parent."""
    if not parent_execution_id or not execution_id:
        return
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    row = session.get(AIExecutionModel, execution_id)
    if row is None:
        return
    row.metadata_json = {**(row.metadata_json or {}), PARENT_KEY: str(parent_execution_id)}
    session.commit()
