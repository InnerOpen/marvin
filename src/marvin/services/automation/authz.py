"""Per-action authorization for Flavor B automations — *definer's rights*.

An automation is workspace config that only an ADMIN/OWNER may author (creation is role-gated in the
controller). So its actions run under the **author's** authority (``WorkspaceAutomationModel.created_by``),
NOT under whoever happens to trip its trigger. The triggering ``user_id`` is provenance only.

Without this, ``user_id`` was threaded as ``triggered_by`` but never checked, so an operation's
``min_role`` (and the implicit privilege of a handler/webhook action) was *silently unenforced* for
automation-run actions: an AUTHOR publishing an entry could trip an admin-authored automation that
runs a privileged reindex/rebuild handler or exfiltrates workspace data to a webhook, all under full
workspace authority.

This module resolves the author's **current** role at execution time and gates each action against
the role it needs. The check is fail-*closed*: if the author was demoted or removed, the privileged
actions their automation used to be allowed to run now fail cleanly (the engine logs + records it)
rather than continuing to run with stale authority.
"""

from marvin.services.ai.operations.base import (
    ROLE_ADMIN,
    ROLE_AUTHOR,
    ROLE_EDITOR,
    ROLE_OWNER,
    ROLE_VIEWER,
)

__all__ = [
    "ROLE_VIEWER",
    "ROLE_AUTHOR",
    "ROLE_EDITOR",
    "ROLE_ADMIN",
    "ROLE_OWNER",
    "ENTRY_ACTION_MIN_ROLE",
    "EMIT_EVENT_MIN_ROLE",
    "HANDLER_MIN_ROLE",
    "WEBHOOK_MIN_ROLE",
    "INTEGRATION_ACTION_MIN_ROLE",
    "resolve_authorizer_role",
    "require_role",
]

from .actions.base import AutomationActionError

# Role each non-AI action kind requires of the automation's author. (The `operation` kind gates on
# the AIOperation's own declared `min_role`, so it isn't listed here.) These document the privilege
# each action wields and only bite when the author's live role has fallen below it.
ENTRY_ACTION_MIN_ROLE = ROLE_AUTHOR  # publish/unpublish/archive/restore — a content mutation
EMIT_EVENT_MIN_ROLE = ROLE_AUTHOR  # chain an internal event — the authoring privilege
HANDLER_MIN_ROLE = ROLE_ADMIN  # run a maintenance/index/rebuild job
WEBHOOK_MIN_ROLE = ROLE_ADMIN  # send workspace data to an external endpoint
INTEGRATION_ACTION_MIN_ROLE = ROLE_ADMIN  # call an external service with the workspace's integration credentials


def resolve_authorizer_role(session, group_id, author_id) -> int:
    """The automation author's *current* numeric role in this workspace — the authority its actions
    run under. Platform admins → OWNER; a member → their role's value; a removed/unknown member → 0
    (fail closed, so a demoted author's privileged actions stop working).

    ``author_id is None`` (legacy/system automations created before ``created_by``, or through a path
    that didn't record it) → OWNER: only an admin could have created it, and there's no principal to
    downgrade. New automations always record ``created_by``, so this is a back-compat allowance, not
    a hole.
    """
    if author_id is None:
        return ROLE_OWNER
    from marvin.db.models.users.users import Users

    author = session.get(Users, author_id)
    if author is None:
        return 0
    if getattr(author, "admin", False):
        return ROLE_OWNER
    role = author.get_workspace_role(group_id)  # str-normalized membership lookup
    return role.value if role is not None else 0


def require_role(authorizer_role: int, needed: int, what: str) -> None:
    """Raise :class:`AutomationActionError` if the author's role is below ``needed``.

    ``what`` names the action for the message (recorded on the execution row), e.g.
    ``"handler 'ai_reindex_embeddings'"``.
    """
    if authorizer_role < needed:
        raise AutomationActionError(
            f"{what} requires role {needed}, but the automation's author has role {authorizer_role} "
            "in this workspace. The author may have been removed or downgraded; an admin must re-own "
            "or re-author this automation."
        )
