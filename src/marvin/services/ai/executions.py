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


# ── Who sees which runs ────────────────────────────────────────────────
# Workspace OWNERs/ADMINs (and platform super admins) see every run in the workspace; other members see
# only the runs they triggered. A run with no user (system, workflow or scheduled) is admin-only.


def sees_every_run(user, role: int) -> bool:
    """True for a workspace OWNER/ADMIN (`role` is the caller's numeric workspace role) or a platform super admin."""
    from marvin.db.models.users.roles import PlatformRole

    from .operations.base import ROLE_ADMIN

    return role >= ROLE_ADMIN or getattr(user, "platform_role", None) == PlatformRole.SUPER_ADMIN


def visible_runs(query, *, sees_all: bool, user_id):
    """Narrow an AIExecutionModel query to the runs the caller may see."""
    import sqlalchemy as sa

    from marvin.db.models.groups.ai_executions import AIExecutionModel

    if sees_all:
        return query
    if user_id is None:
        return query.filter(sa.false())
    return query.filter(AIExecutionModel.triggered_by == user_id)


def may_see_run(row, *, sees_all: bool, user_id) -> bool:
    """Whether the caller may see this execution row (the single-row form of `visible_runs`)."""
    if sees_all:
        return True
    return user_id is not None and row.triggered_by is not None and str(row.triggered_by) == str(user_id)
