"""A workspace's notifications — Settings → Automation → Notifications.

The bell and the Event Log always get a workspace's events. These settings also send the ones that need a
person — a workflow or scheduled task failing, a connection that needs attention, the Trash about to empty —
somewhere people look when they aren't in Marvin: email to the workspace's owners and admins (or a list), push
to the devices of the owners and admins who turned it on (when the server has Web Push; not the Trash reminder,
whose push each person chooses in their Profile), and any message-capable
action on one of the workspace's own connections (Slack's ``send_message`` with its channel, Apprise's
``notify``, any notify plugin). Each channel takes every kind, or only the ones chosen for it. The settings,
channels and message are services/alerting.py's, shared with platform alerts; this module is the
workspace's scope of it and its delivery.

One alert per incident, the way backups alert: a workflow (or scheduled task) that keeps failing sends one
alert, and its next success sends one "working again" note to the channels that got the alert
(``workspace_alert_incidents``). A workflow failure an integration's error policy handled (sent to review,
retry scheduled) is not an incident: the integration's own "needs attention" alert covers what a person must
do. Integration alerts already come once per incident, with reminders and a "resolved" event
(services/integrations/errors.py); each records the channels it went out through (``channels["notify"]``)
and its "working again" notice goes back through those. AI operation and webhook delivery failures send one
alert each (they are off by default).

Delivery hangs off the event bus (``WorkspaceAlertListener``) and only ever sends this workspace's own
events: never one dispatched without a workspace, never a platform-scope event (those are Admin → Platform
alerts'). Stored on ``group_preferences``: ``notifications_json`` (what an admin chose; null takes the
defaults) and ``notifications_status_json`` (each channel's last delivery, written by delivery only).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger
from marvin.services import alerting, web_push
from marvin.services.alerting import AlertKind, AlertMessage, AlertSettings, event_data

logger = get_logger(__name__)

PAGE_PATH = "/automation/notifications"
TEST_TITLE = "Test notification from Marvin"

WORKFLOW_FAILED = "workflow_failed"
SCHEDULED_TASK_FAILED = "scheduled_task_failed"
INTEGRATION_ATTENTION = "integration_attention"
TRASH_SOON = "trash_auto_empty_soon"

KINDS: tuple[AlertKind, ...] = (
    AlertKind(
        WORKFLOW_FAILED,
        "Workflow failed",
        "automation_failed",
        "A workflow run failed. One alert while it keeps failing, and a note when it next runs successfully. "
        "A failure an integration's error policy handled doesn't alert.",
        "/automation/workflows",
        recovered_by="automation_ran",
    ),
    AlertKind(
        SCHEDULED_TASK_FAILED,
        "Scheduled task failed",
        "scheduled_task_failed",
        "A scheduled task failed. One alert while it keeps failing, and a note when it next succeeds.",
        "/workspace/scheduled-tasks",
        recovered_by="scheduled_task_completed",
    ),
    AlertKind(
        INTEGRATION_ATTENTION,
        "Integration needs attention",
        "integration_attention_needed",
        "A connection needs a person (expired credentials, a misconfigured account): when it opens, a reminder while "
        "it stays open, and a note when it works again.",
        "/workspace/settings/integration-health",
        recovered_by="integration_attention_resolved",
    ),
    AlertKind(
        "ai_operation_failed",
        "AI operation failed",
        "ai_operation_failed",
        "An AI operation failed. Each failure sends one.",
        "/workspace/settings/ai-executions",
        default=False,
    ),
    AlertKind(
        "webhook_delivery_failed",
        "Webhook delivery failed",
        "webhook_delivery_failed",
        "An outgoing webhook couldn't deliver after its retries. Each failure sends one.",
        "/automation/webhooks/log",
        default=False,
    ),
    AlertKind(
        TRASH_SOON,
        "Trash emptying soon",
        "trash_auto_empty_soon",
        "The Trash's auto-empty will delete items forever within a day. At most one a day. By email and connections; "
        "push for it is each owner's and admin's own choice (Profile → Notifications → Trash reminders).",
        "/workspace/collections",
        default=False,
        push=False,
    ),
)
KINDS_BY_KEY: dict[str, AlertKind] = {k.key: k for k in KINDS}

INCIDENTS: dict[str, tuple[str, str]] = {
    WORKFLOW_FAILED: ("automation", "Workflow"),
    SCHEDULED_TASK_FAILED: ("scheduled_task", "Scheduled task"),
}
"""The kinds alerting once per incident here: kind → (incident key prefix, what it is called)."""

EVENT_TYPES: frozenset[str] = frozenset({k.event_type for k in KINDS} | {k.recovered_by for k in KINDS if k.recovered_by})
"""What the listener looks at; any other event costs it nothing."""


# --------------------------------------------------------------------------------------------------
# The workspace's scope
# --------------------------------------------------------------------------------------------------


def _prefs(session: Session, group_id):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    return session.query(GroupPreferencesModel).filter_by(group_id=group_id).first()


def _write_prefs(session: Session, group_id, column: str, value: dict) -> None:
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = _prefs(session, group_id)
    if prefs is None:
        prefs = GroupPreferencesModel(session=session, group_id=group_id)
        session.add(prefs)
    setattr(prefs, column, value)
    session.commit()


def admin_emails(session: Session, group_id) -> list[str]:
    """The workspace's owners' and admins' email addresses."""
    from sqlalchemy import select

    from marvin.db.models.users import Users
    from marvin.db.models.users.roles import WorkspaceRole
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    stmt = (
        select(Users.email)
        .join(WorkspaceMembers, WorkspaceMembers.user_id == Users.id)
        .where(WorkspaceMembers.group_id == group_id, WorkspaceMembers.workspace_role.in_([WorkspaceRole.OWNER, WorkspaceRole.ADMIN]))
        .order_by(Users.email)
    )
    return [email for email in session.execute(stmt).scalars().all() if email]


def smtp_ready(session: Session, group_id) -> bool:
    """The workspace has an active SMTP profile, or the platform's sender can send (its fallback)."""
    from marvin.services.email.email_senders import email_ready

    return email_ready(group_id, session)


class WorkspaceScope(alerting.AlertScope):
    """One workspace's notifications: stored on its preferences, routes through its own connections, email to
    its owners and admins through its SMTP profile (or the platform's)."""

    name = "workspace notifications"
    kinds = KINDS
    page = "Settings → Automation → Notifications"
    page_path = PAGE_PATH
    test_title = TEST_TITLE
    everyone = "every owner and admin"
    nobody = "no owner or admin of this workspace has an email address"
    email_setup = "email isn't set up (Settings → Email → SMTP, or the platform's email settings)"
    where = "this workspace"
    per_channel_kinds = True
    push_category = web_push.WORKSPACE_ALERTS
    push_everyone = "owners and admins who turned on push with “Workspace alerts” in their Profile"

    def __init__(self, group_id) -> None:
        self.group_id = group_id

    def stored_settings(self, session: Session) -> dict | None:
        prefs = _prefs(session, self.group_id)
        return prefs.notifications_json if prefs is not None else None

    def store_settings(self, session: Session, stored: dict) -> None:
        _write_prefs(session, self.group_id, "notifications_json", stored)

    def stored_status(self, session: Session) -> dict:
        prefs = _prefs(session, self.group_id)
        return (prefs.notifications_status_json if prefs is not None else None) or {}

    def store_status(self, session: Session, status: dict) -> None:
        _write_prefs(session, self.group_id, "notifications_status_json", status)

    def workspace(self, session: Session):
        from marvin.db.models.groups import Groups

        return session.get(Groups, self.group_id)

    def default_recipients(self, session: Session) -> list[str]:
        return admin_emails(session, self.group_id)

    def email_ready(self, session: Session) -> bool:
        return smtp_ready(session, self.group_id)

    def push_people(self, session: Session) -> list:
        from marvin.db.models.users.roles import WorkspaceRole

        return web_push.workspace_member_ids(session, self.group_id, WorkspaceRole.ADMIN)

    def email_service(self):
        from marvin.services.email.email_service import EmailService

        return EmailService(group_id=str(self.group_id))  # the workspace's SMTP profile, else the platform's

    def scope_label(self, session: Session) -> str:
        workspace = self.workspace(session)
        return f"Workspace — {getattr(workspace, 'name', None) or 'this workspace'}"

    def reason(self, kind: AlertKind) -> str:
        return f"Sent because “{kind.label}” is on in {self.page}."

    def trial_summary(self, channel_label: str) -> str:
        return f"This is a test of the {channel_label} route for this workspace's notifications. Nothing is wrong."


def reminder_hours(session: Session, group_id) -> int:
    """How often an open integration alert is sent again (0 = never)."""
    from marvin.services.integrations.errors import _reminder_hours

    return _reminder_hours(session, group_id)


def set_reminder_hours(session: Session, group_id, hours: int) -> None:
    prefs = _prefs(session, group_id)
    if prefs is not None:
        prefs.integration_alert_reminder_hours = hours
        session.commit()


def load(session: Session, group_id) -> AlertSettings:
    return alerting.load(WorkspaceScope(group_id), session)


def channels_for(session: Session, group_id, kind: str) -> list[str]:
    """The channels an alert of ``kind`` goes to right now (none while the kind is off)."""
    settings = load(session, group_id)
    return settings.channels_for(kind) if settings.types.get(kind) else []


# --------------------------------------------------------------------------------------------------
# Incidents: one alert while something keeps failing, one note when it works again
# --------------------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _open_incident(session: Session, group_id, key: str, kind: str, subject: str | None, channels: list[str]) -> bool:
    """Open the incident — True: this failure alerts — or count another failure on the open one (False)."""
    from marvin.db.models.groups.alert_incidents import WorkspaceAlertIncidentModel

    now = _now()
    row = session.query(WorkspaceAlertIncidentModel).filter_by(group_id=group_id, key=key).first()
    if row is not None:
        row.count = (row.count or 0) + 1
        row.last_at = now
        session.commit()
        return False
    session.add(
        WorkspaceAlertIncidentModel(
            session=session, group_id=group_id, key=key, kind=kind, subject=subject, count=1, opened_at=now, last_at=now, channels=channels
        )
    )
    try:
        session.commit()
    except IntegrityError:  # opened concurrently — count it on that one instead
        session.rollback()
        return _open_incident(session, group_id, key, kind, subject, channels)
    return True


def _close_incident(session: Session, group_id, key: str) -> SimpleNamespace | None:
    """End the open incident, if there is one; what it was, for its "working again" note."""
    from marvin.db.models.groups.alert_incidents import WorkspaceAlertIncidentModel

    query = session.query(WorkspaceAlertIncidentModel).filter_by(group_id=group_id, key=key)
    row = query.first()
    if row is None:
        return None
    ended = SimpleNamespace(kind=row.kind, subject=row.subject, count=row.count, opened_at=row.opened_at, channels=list(row.channels or []))
    gone = query.filter(WorkspaceAlertIncidentModel.id == row.id).delete(synchronize_session=False)
    session.commit()
    return ended if gone else None  # closed concurrently: that one sends the note


def passing_blip(data: dict) -> bool:
    """A scheduled run's network blip not announced yet (services/scheduled_tasks/blips.py decided, at the failure)."""
    return data.get("alert_deferred") is True


def _incident_key(kind: str, data: dict) -> str | None:
    prefix = INCIDENTS[kind][0]
    subject_id = data.get("automation_id") if kind == WORKFLOW_FAILED else data.get("task_id")
    return f"{prefix}:{subject_id}" if subject_id else None


# --------------------------------------------------------------------------------------------------
# The message
# --------------------------------------------------------------------------------------------------


def _subject(kind: str, data: dict) -> str | None:
    if kind == WORKFLOW_FAILED:
        return data.get("automation_name") or data.get("automation_slug")
    if kind == SCHEDULED_TASK_FAILED:
        return data.get("task_name")
    if kind == "webhook_delivery_failed":
        return data.get("webhook_name")
    if kind == "ai_operation_failed":
        return data.get("operation_slug")
    return None


def _link_path(kind: AlertKind, data: dict) -> str:
    if kind.key == WORKFLOW_FAILED and data.get("automation_id"):
        return f"{kind.link_path}?workflow={data['automation_id']}"
    if kind.key == SCHEDULED_TASK_FAILED and data.get("task_id"):
        return f"{kind.link_path}/{data['task_id']}"
    if kind.key == TRASH_SOON and data.get("trash_collection_id"):
        return f"{kind.link_path}/{data['trash_collection_id']}"
    return kind.link_path


def message_for(scope: WorkspaceScope, session: Session, kind: AlertKind, event, data: dict) -> AlertMessage:
    """The alert for one of the workspace's events: what failed, why, and where to look."""
    message = getattr(event, "message", None)
    subject = _subject(kind.key, data)
    if kind.key == INTEGRATION_ATTENTION:
        title, summary, detail = data.get("title") or kind.label, data.get("summary") or kind.description, None
    elif kind.key == TRASH_SOON:
        total = int(data.get("total") or 0)
        title = f"{total} item{'' if total == 1 else 's'} will be deleted forever tomorrow"
        summary = (
            f"{data.get('entries', 0)} entries, {data.get('assets', 0)} assets and {data.get('resources', 0)} resources reach "
            f"{data.get('days')} days in the Trash within a day, and its auto-empty deletes them then. Restore anything you "
            "want to keep."
        )
        detail = None
    else:
        title = f"{kind.label}: {subject}" if subject else (getattr(message, "title", None) or kind.label)
        summary = getattr(message, "body", None) or kind.description
        error = data.get("error") or data.get("error_message")
        detail = error if error and error not in summary else None
    return alerting.build_message(
        title=title, summary=summary, detail=detail, reason=scope.reason(kind), link_path=_link_path(kind, data), scope=scope.scope_label(session)
    )


def _recovered_message(scope: WorkspaceScope, session: Session, kind: AlertKind, ended: SimpleNamespace, data: dict) -> AlertMessage:
    noun = INCIDENTS[kind.key][1]
    subject = _subject(kind.key, data) or ended.subject or noun.lower()
    opened = ended.opened_at.replace(tzinfo=UTC) if ended.opened_at and ended.opened_at.tzinfo is None else ended.opened_at
    failures = f"{ended.count} failed run{'s' if ended.count != 1 else ''}"
    return alerting.build_message(
        title=f"{noun} working again: {subject}",
        summary=f"{subject} succeeded after {failures}" + (f" since {opened:%Y-%m-%d %H:%M} UTC." if opened else "."),
        reason=f"Sent to the channels that got its “{kind.label}” alert.",
        link_path=_link_path(kind, data),
        scope=scope.scope_label(session),
    )


# --------------------------------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------------------------------


def wants(group_id, event) -> bool:
    """Whether the event is one to look at (no database): only this workspace's own, workspace-scope events of
    the kinds above — never a platform event, never one dispatched without a workspace."""
    from marvin.services.events.event_catalog import is_platform_event

    name = event.event_type.name
    if group_id is None or name not in EVENT_TYPES or is_platform_event(name):
        return False
    workspace_id = getattr(event, "workspace_id", None)
    return workspace_id is None or str(workspace_id) == str(group_id)


def deliver(session: Session, group_id, event) -> dict[str, dict]:
    """Send one of the workspace's events where its notifications say, once per incident. Returns the statuses."""
    if not wants(group_id, event):
        return {}
    name = event.event_type.name
    data = event_data(event)
    scope = WorkspaceScope(group_id)

    recovers = next((k for k in KINDS if k.recovered_by == name), None)
    if recovers is not None:
        return _deliver_recovery(scope, session, recovers, event, data)

    settings = alerting.load(scope, session)
    kind = settings.enabled_kind(name, data)
    if kind is None:
        return {}
    if kind.key == WORKFLOW_FAILED and data.get("handled"):
        return {}  # the integration's error policy took it in hand; its own alert says what a person must do
    if kind.key == SCHEDULED_TASK_FAILED and passing_blip(data):
        return {}  # a network blip: no incident yet, so a success next run sends no "working again" either
    channels = settings.channels_for(kind.key)
    if kind.key in INCIDENTS:
        key = _incident_key(kind.key, data)
        if key is not None and not _open_incident(session, group_id, key, kind.key, _subject(kind.key, data), channels):
            return {}  # still failing: it already alerted
    if not channels:
        return {}
    return alerting.send(scope, session, settings, message_for(scope, session, kind, event, data), channels, event_type=name, test=False)


def _deliver_recovery(scope: WorkspaceScope, session: Session, kind: AlertKind, event, data: dict) -> dict[str, dict]:
    """The note that something works again, to the channels its alert went out through — still saved, even if
    turned off since."""
    if kind.key == INTEGRATION_ATTENTION:
        channels = list(((data.get("channels") or {}).get("notify")) or [])
        if not channels:
            return {}
        settings = alerting.load(scope, session)
        message = message_for(scope, session, kind, event, data)
    else:
        key = _incident_key(kind.key, data)
        ended = _close_incident(session, scope.group_id, key) if key else None
        if ended is None or not ended.channels:
            return {}
        channels = ended.channels
        settings = alerting.load(scope, session)
        message = _recovered_message(scope, session, kind, ended, data)
    return alerting.send(scope, session, settings, message, channels, event_type=event.event_type.name, test=False)


def send_test(session: Session, group_id, channel: str, by: str | None = None) -> dict:
    """Send the test message to one saved channel (``email`` or a route id), even when it's off."""
    return alerting.send_test(WorkspaceScope(group_id), session, channel, by)
