"""Push for what the bell asks a person to act on, and for AI approvals (services/web_push.py sends).

The bell (the activity toasts) shows a workspace's events as they happen; most are only news. A few need a
person, and those also go to the phones and browsers of people who turned push on (Profile → Notifications):

  * **AI approvals** — an agent run parked on "ask first" (``approval_requested``) goes to the person whose
    run it is, and only them, linking to the Ask thread where they decide; when everything it waits on can be
    undone, with Approve / Deny buttons (services/push_actions.py);
  * **workspace activity** — a form submission (not one flagged as spam) and a scheduled publish that's
    waiting (``entry_scheduled_publish_blocked``) go to the workspace's editors and above, except whoever
    caused it;
  * **Trash reminders** — the day before the Trash's auto-empty deletes items forever
    (``trash_auto_empty_soon``, once a day per workspace) goes to its owners and admins, opening the Trash.

Failures (a workflow, a scheduled task, a connection) are not here: they go through the Push channel of
Settings → Automation → Notifications (services/workspace_alerts.py), once per incident. Each person's
preferences decide what reaches them; the message is a title, a line and a link — never the submission or
the tool call's arguments.

Hangs off the event bus (``PushNotificationListener``): nothing to do, and no database read, unless Web Push
is configured and the event is one of the above, dispatched in its own workspace.
"""

from __future__ import annotations

from urllib.parse import quote

from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger
from marvin.services import web_push
from marvin.services.alerting import event_data

logger = get_logger(__name__)

ASK_PATH = "/workspace/settings/ai-ask"
"""The Ask page (frontend lib/marvin/pending.ts askThreadHref)."""
APPROVAL_REQUESTED = "approval_requested"
ACTIVITY_TITLES = {
    "form_submission_received": "Form submission",
    "entry_scheduled_publish_blocked": "Scheduled publish waiting",
}
TRASH_SOON = "trash_auto_empty_soon"
EVENT_TYPES = frozenset(ACTIVITY_TITLES) | {APPROVAL_REQUESTED, TRASH_SOON}


def wants(group_id, event) -> bool:
    """Whether to look at the event (no database): push is configured and it's one of the workspace's own events above."""
    from marvin.services.events.event_catalog import is_platform_event

    name = event.event_type.name
    if group_id is None or name not in EVENT_TYPES or is_platform_event(name) or not web_push.configured():
        return False
    workspace_id = getattr(event, "workspace_id", None)
    return workspace_id is None or str(workspace_id) == str(group_id)


def _line(event) -> str:
    return getattr(getattr(event, "message", None), "body", None) or ""


def _workspace_name(session: Session, group_id, data: dict) -> str | None:
    if data.get("workspace_name"):
        return data["workspace_name"]
    from marvin.db.models.groups import Groups

    group = session.get(Groups, group_id)
    return getattr(group, "name", None)


def _thread_id(event, data: dict):
    return data.get("thread_id") or (event.entity_id if getattr(event, "entity_type", None) == "ai_thread" else None)


def approval_message(event, data: dict, token: str | None = None) -> web_push.PushMessage:
    thread_id = _thread_id(event, data)
    url = f"{ASK_PATH}?thread={quote(str(thread_id))}" if thread_id else ASK_PATH
    return web_push.PushMessage(
        title="Waiting for your approval",
        body=_line(event) or "An agent is waiting for your OK before it acts.",
        url=url,
        tag=f"approval:{thread_id}" if thread_id else "approval",
        urgency="high",
        approval={"id": str(thread_id), "token": token} if token and thread_id else None,
    )


def _approval_token(session: Session, event, data: dict, owner) -> str | None:
    """The one-tap token, when the parked run is one a tap may approve and its owner takes the push."""
    from marvin.db.models.groups.ai_threads import AIThreadModel
    from marvin.services import push_actions

    thread_id = push_actions._uuid(_thread_id(event, data))
    if thread_id is None or not web_push.push_ready_users(session, [owner], web_push.APPROVALS):
        return None
    try:
        root = session.get(AIThreadModel, thread_id)
        return push_actions.mint(session, root, owner) if root is not None else None
    except Exception:  # noqa: BLE001 — without a token the push still opens the thread
        session.rollback()
        logger.exception("Web Push: could not mint an approval action token")
        return None


def activity_message(session: Session, group_id, event, data: dict) -> web_push.PushMessage:
    name = event.event_type.name
    entry_id = event.entity_id if getattr(event, "entity_type", None) == "entry" else None
    from marvin.services.ui_links import ENTRY_PATH

    workspace = _workspace_name(session, group_id, data)
    title = ACTIVITY_TITLES[name] + (f" · {workspace}" if workspace else "")
    return web_push.PushMessage(
        title=title,
        body=_line(event),
        url=ENTRY_PATH.format(entry_id=entry_id) if entry_id else "/workspace/entries",
        tag=f"{name}:{entry_id or event.entity_id or ''}",
    )


def trash_message(session: Session, group_id, data: dict) -> web_push.PushMessage:
    total = int(data.get("total") or 0)
    workspace = _workspace_name(session, group_id, data)
    what = f"{total} item{'' if total == 1 else 's'} will be deleted forever tomorrow"
    trash = data.get("trash_collection_id")
    return web_push.PushMessage(
        title=f"{workspace}: {what}" if workspace else what[:1].upper() + what[1:],
        body="Open the Trash to restore anything you want to keep.",
        url=f"/workspace/collections/{quote(str(trash))}" if trash else "/workspace/collections",
        tag=f"trash-reminder:{group_id}",
    )


def deliver(session: Session, group_id, event) -> web_push.SendResult:
    """Push one of the workspace's events to the people it's for. Returns what was sent."""
    if not wants(group_id, event):
        return web_push.SendResult()
    name = event.event_type.name
    data = event_data(event)
    if name == APPROVAL_REQUESTED:
        owner = getattr(event, "user_id", None)
        if owner is None:
            return web_push.SendResult()
        token = _approval_token(session, event, data, owner)
        return web_push.send_to_users(session, [owner], web_push.APPROVALS, approval_message(event, data, token))
    from marvin.db.models.users.roles import WorkspaceRole

    if name == TRASH_SOON:
        admins = web_push.workspace_member_ids(session, group_id, WorkspaceRole.ADMIN)
        return web_push.send_to_users(session, admins, web_push.TRASH_REMINDERS, trash_message(session, group_id, data))
    if name == "form_submission_received" and data.get("flagged"):
        return web_push.SendResult()  # suspected spam waits in review without waking anyone

    actor = str(getattr(event, "user_id", None) or "")
    people = [u for u in web_push.workspace_member_ids(session, group_id, WorkspaceRole.EDITOR) if str(u) != actor]
    return web_push.send_to_users(session, people, web_push.ACTIVITY, activity_message(session, group_id, event, data))
