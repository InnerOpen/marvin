"""Platform alerts outside the bell — Admin → Platform alerts.

Super admins see platform events (backups, storage, security) in the bell and on Admin → Events. These
settings also send the ones that matter somewhere people look when they aren't in Marvin:

  * **email** — built in and on by default: the platform SMTP settings (Admin → Email settings), to every
    super admin unless an explicit list is set. Without SMTP nothing is sent, and the channel's last
    delivery says so;
  * **push** — when the server has Web Push (VAPID): to the devices of the super admins who turned push on
    with "Platform alerts" in their Profile;
  * **integration routes** — any action that can carry a message (``alert_routing.message_actions``: Slack's
    ``send_message``, Apprise's ``notify``, whatever a plugin declares — never a list of names) on a
    connection in the **platform workspace**. Integrations are connected per workspace and the admin area
    configures none, so platform alerts borrow that one workspace's connections. Without it, routes are
    unavailable and email still works.

Delivery hangs off the event bus (``PlatformAlertListener``): one dispatched event, one attempt per
enabled channel — after the backup check's own once-per-incident rule, so this adds no dedupe and no
retries. A channel that fails is logged and its "last delivery" shows why; it never stops the others.
Messages carry the event's title and summary, the scope, why it was sent and a link to the admin page —
scrubbed like a backup error, never the event's raw payload.

The settings, the channels and the message are services/alerting.py's, shared with each workspace's
notifications; this module is the platform's scope of it (:class:`PlatformScope`) and its entry points.

Stored in ``platform_settings`` under ``platform_alerts`` (what an admin chose) and
``platform_alerts_status`` (each channel's last delivery, written by delivery, so saving never races it).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from marvin.services import alerting, web_push
from marvin.services.alerting import (  # noqa: F401 — the platform alerts' public names
    EMAIL_CHANNEL,
    FAILED,
    MAX_TEXT,
    PUSH_CHANNEL,
    SENT,
    SKIPPED,
    AlertKind,
    AlertMessage,
    AlertSettings,
    Delivery,
    InvalidAlertSettings,
    Route,
    Target,
    event_data,
    targets,
)
from marvin.services.platform_settings import PlatformSettingsService

SETTINGS_KEY = "platform_alerts"
STATUS_KEY = "platform_alerts_status"
SCOPE = "Platform — all workspaces"
PAGE_PATH = "/admin/alerts"
TEST_TITLE = "Test alert from Marvin admin"

KINDS: tuple[AlertKind, ...] = (
    AlertKind(
        "backup_failed",
        "Backup failed",
        "backup_failed",
        "A backup target's run failed, or saved the database but not everything else.",
        "/admin/backup-health",
        reasons=frozenset({"failed", "partial"}),
    ),
    AlertKind(
        "backup_overdue",
        "Backup overdue",
        "backup_failed",
        "A backup target has had no successful run inside its window.",
        "/admin/backup-health",
        reasons=frozenset({"overdue"}),
    ),
    AlertKind(
        "backup_recovered",
        "Backup recovered",
        "backup_completed",
        "The successful run that ends a failed or overdue backup. Routine successful runs never alert.",
        "/admin/backup-health",
        reasons=frozenset({"recovered"}),
    ),
    AlertKind(
        "storage_provider_changed",
        "Storage provider changed",
        "storage_provider_changed",
        "An admin changed where new uploads are stored.",
        "/admin/storage",
    ),
    AlertKind(
        "storage_public_domain_changed",
        "Workspace asset domain changed",
        "storage_public_domain_changed",
        "An admin changed the public domain a workspace's remote assets are served from.",
        "/admin/storage",
        default=False,
    ),
    AlertKind(
        "login_failed_multiple_times",
        "Repeated failed logins",
        "login_failed_multiple_times",
        "Several failed logins in a row on one account.",
        "/admin/events",
    ),
    AlertKind(
        "suspicious_activity_detected",
        "Suspicious activity",
        "suspicious_activity_detected",
        "Marvin flagged activity as suspicious.",
        "/admin/events",
    ),
)
KINDS_BY_KEY: dict[str, AlertKind] = {k.key: k for k in KINDS}
ALERT_EVENT_TYPES: frozenset[str] = frozenset(k.event_type for k in KINDS)
"""What the listener looks at; any other event costs it nothing."""


def _platform_workspace(session: Session):
    """The workspace whose integration connections platform alerts may use, or None.

    The platform workspace, found by its marker whatever it is called (services/group/platform_workspace)."""
    from marvin.services.group.platform_workspace import PlatformWorkspaceMissing, platform_workspace

    try:
        return platform_workspace(session)
    except PlatformWorkspaceMissing:
        return None


def super_admin_emails(session: Session) -> list[str]:
    from marvin.db.models.users.roles import PlatformRole
    from marvin.db.models.users.users import Users

    rows = session.query(Users.email).filter(Users.platform_role == PlatformRole.SUPER_ADMIN).order_by(Users.email).all()
    return [email for (email,) in rows if email]


def smtp_ready() -> bool:
    from marvin.core.config import get_app_settings

    return bool(get_app_settings().SMTP_ENABLED)


class PlatformScope(alerting.AlertScope):
    """Platform alerts: stored in ``platform_settings``, routes through the platform workspace's connections,
    email to every super admin through the platform SMTP settings."""

    name = "platform alerts"
    kinds = KINDS
    page = "Admin → Platform alerts"
    page_path = PAGE_PATH
    test_title = TEST_TITLE
    everyone = "every super admin"
    nobody = "no super admin has an email address"
    email_setup = "SMTP isn't configured (Admin → Email settings)"
    where = "the platform workspace"
    push_category = web_push.PLATFORM_ALERTS
    push_everyone = "super admins who turned on push with “Platform alerts” in their Profile"

    def stored_settings(self, session: Session) -> dict | None:
        return PlatformSettingsService(session).get(SETTINGS_KEY)

    def store_settings(self, session: Session, stored: dict) -> None:
        PlatformSettingsService(session).set(SETTINGS_KEY, stored)

    def stored_status(self, session: Session) -> dict:
        return PlatformSettingsService(session).get(STATUS_KEY) or {}

    def store_status(self, session: Session, status: dict) -> None:
        PlatformSettingsService(session).set(STATUS_KEY, status)

    def workspace(self, session: Session):
        return _platform_workspace(session)

    def default_recipients(self, session: Session) -> list[str]:
        return super_admin_emails(session)

    def email_ready(self, session: Session) -> bool:
        return smtp_ready()

    def push_people(self, session: Session) -> list:
        return web_push.super_admin_ids(session)

    def email_service(self):
        from marvin.services.email.email_service import EmailService

        return EmailService()  # no workspace: the platform SMTP settings

    def scope_label(self, session: Session) -> str:
        return SCOPE

    def reason(self, kind: AlertKind) -> str:
        return f"Sent because “{kind.label}” alerts are on in {self.page}."

    def trial_summary(self, channel_label: str) -> str:
        return f"This is a test of the {channel_label} route for platform alerts. Nothing is wrong."


PLATFORM = PlatformScope()


def load(session: Session) -> AlertSettings:
    return alerting.load(PLATFORM, session)


def save(session: Session, settings: AlertSettings) -> None:
    alerting.save(PLATFORM, session, settings)


def statuses(session: Session) -> dict[str, dict]:
    return alerting.statuses(PLATFORM, session)


def validate(
    session: Session, *, types: dict[str, bool], email_enabled: bool, recipients: list[str] | None, routes: list[dict], push: dict | None = None
) -> AlertSettings:
    """What the admin asked for as settings, or InvalidAlertSettings. Routes must name a message-capable
    action on a connection in the platform workspace. ``push`` ({enabled}) left out keeps it as it is."""
    return alerting.validate(PLATFORM, session, types=types, email_enabled=email_enabled, recipients=recipients, routes=routes, push=push)


def describe_changes(session: Session, old: AlertSettings, new: AlertSettings) -> list[str]:
    return alerting.describe_changes(PLATFORM, session, old, new)


def build_message(*, title: str, summary: str, reason: str, link_path: str, detail: str | None = None) -> AlertMessage:
    return alerting.build_message(title=title, summary=summary, reason=reason, link_path=link_path, detail=detail, scope=SCOPE)


def message_for(kind: AlertKind, event, data: dict) -> AlertMessage:
    """The alert for one platform event: its catalog title, its message, the backup error if there is one."""
    message = getattr(event, "message", None)
    title = getattr(message, "title", None) or kind.label
    summary = getattr(message, "body", None) or kind.description
    detail = data.get("error_message") if kind.event_type.startswith("backup_") else None
    return build_message(title=title, summary=summary, detail=detail, reason=PLATFORM.reason(kind), link_path=kind.link_path)


def send_email(session: Session, settings: AlertSettings, message: AlertMessage) -> Delivery:
    """Email through the platform SMTP settings, to the explicit list or every super admin."""
    return alerting.send_email(PLATFORM, session, settings, message)


def send_route(session: Session, route: Route, message: AlertMessage, workspace=None) -> Delivery:
    """Run the route's action on its platform-workspace connection with the message filled in."""
    return alerting.send_route(PLATFORM, session, route, message, workspace)


def deliver(session: Session, event, data: dict | None = None) -> dict[str, dict]:
    """Send one dispatched platform event to every enabled channel, if its kind is on. Returns the statuses."""
    event_type = event.event_type.name
    if event_type not in ALERT_EVENT_TYPES:
        return {}
    data = data if data is not None else event_data(event)
    settings = load(session)
    kind = settings.enabled_kind(event_type, data)
    if kind is None:
        return {}
    message = message_for(kind, event, data)
    return alerting.send(PLATFORM, session, settings, message, settings.channels_for(kind.key), event_type=event_type, test=False)


def send_test(session: Session, channel: str, by: str | None = None) -> dict:
    """Send the test message to one saved channel (``email``, ``push`` or a route id), even when it's off."""
    return alerting.send_test(PLATFORM, session, channel, by)
