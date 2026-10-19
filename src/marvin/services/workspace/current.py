"""Which workspace a user is working in right now — or none.

A user may have no home workspace and no memberships (Admin-created, OIDC and LDAP sign-ups start that way, and a
super admin on a fresh install has none), so "the current workspace" can be nothing. Every place that used to read
``active_group_id or group_id`` asks here instead.
"""

from pydantic import UUID4
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marvin.db.models.groups import Groups
from marvin.db.models.users.roles import PlatformRole

NO_WORKSPACE = "no_workspace"
"""The ``code`` of the 409 a workspace-scoped route answers with when the user has no workspace."""


def current_workspace_id(user, session: Session) -> UUID4 | None:
    """The workspace ``user`` is working in, in this order, or ``None``:

    1. their active workspace, if they can still reach it;
    2. their home workspace, if they are a member of it or a super admin;
    3. the first workspace they are a member of, by name.

    A super admin reaches every workspace, so for them 1 and 2 hold whenever the id is set (deleting a workspace clears
    both columns). Anyone else must be a member. ``user`` is the ORM row or the ``PrivateUser`` schema.
    """
    super_admin = user.platform_role == PlatformRole.SUPER_ADMIN

    for candidate in (user.active_group_id, user.group_id):
        if candidate is not None and (super_admin or user.get_workspace_role(candidate) is not None):
            return candidate

    member_of = [m.group_id for m in user.workspace_memberships]
    if not member_of:
        return None
    return session.execute(select(Groups.id).where(Groups.id.in_(member_of)).order_by(func.lower(Groups.name), Groups.id).limit(1)).scalar()
