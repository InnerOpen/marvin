"""The platform (admin's) workspace: the one group marked ``is_platform``.

Platform alerts and shared services run from it. Find it with :func:`platform_workspace` — never by
name or slug. A super admin can rename it (name and slug); ``settings.DEFAULT_GROUP`` only names it
when a fresh install creates it, so on an existing install that setting is informational.

At most one group carries the marker (partial unique index ``uq_groups_is_platform``). It can't be
deleted and the marker can't be moved or removed through the API.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from marvin.core import root_logger
from marvin.db.models.groups import Groups

logger = root_logger.get_logger()


class PlatformWorkspaceMissing(LookupError):
    """No group is marked as the platform workspace (a database init_db hasn't run against)."""


def platform_workspace(session: Session) -> Groups:
    """The platform (admin's) workspace.

    Raises:
        PlatformWorkspaceMissing: no group carries the marker yet.
    """
    group = session.execute(select(Groups).where(Groups.is_platform.is_(True))).scalar_one_or_none()
    if group is None:
        raise PlatformWorkspaceMissing("No platform workspace: the database hasn't been initialised (init_db creates it).")
    return group


def is_platform_workspace(session: Session, group_id) -> bool:
    """Whether ``group_id`` is the platform workspace."""
    return session.execute(select(Groups.is_platform).where(Groups.id == group_id)).scalar() is True


def log_name_hint(session: Session, configured_name: str) -> None:
    """Startup hint when ``DEFAULT_GROUP`` differs from the platform workspace's actual name.

    The setting only names the workspace on a fresh install; renaming an existing one is the admin
    action (Admin → Workspaces → the platform workspace), so a mismatch is worth a line, not a fix.
    """
    try:
        current = platform_workspace(session).name
    except PlatformWorkspaceMissing:
        return
    if current != configured_name:
        logger.info(
            "Platform workspace is named %r; DEFAULT_GROUP=%r only names it on a fresh install. "
            "To change it, rename the workspace in Admin → Workspaces (PUT /api/admin/groups/{id}).",
            current,
            configured_name,
        )
