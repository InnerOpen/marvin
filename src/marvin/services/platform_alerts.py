"""Platform alerts outside the bell — Admin → Platform alerts.

Super admins see platform events (backups, storage, security) in the bell and on Admin → Events. These
settings also send the ones that matter somewhere people look when they aren't in Marvin:

  * **email** — built in and on by default: the platform SMTP settings (Admin → Email settings), to every
    super admin unless an explicit list is set. Without SMTP nothing is sent, and the channel's last
    delivery says so;
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

Stored in ``platform_settings`` under ``platform_alerts`` (what an admin chose) and
``platform_alerts_status`` (each channel's last delivery, written by delivery, so saving never races it).
"""

from __future__ import annotations

import html
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger
from marvin.services.platform_settings import PlatformSettingsService

logger = get_logger(__name__)

SETTINGS_KEY = "platform_alerts"
STATUS_KEY = "platform_alerts_status"
EMAIL_CHANNEL = "email"
SCOPE = "Platform — all workspaces"
PAGE_PATH = "/admin/alerts"
TEST_TITLE = "Test alert from Marvin admin"
MAX_TEXT = 1500

SENT, FAILED, SKIPPED = "sent", "failed", "skipped"


@dataclass(frozen=True)
class AlertKind:
    """One kind of platform alert an admin turns on or off: an event type, narrowed by the backup
    check's ``reason`` where one event type means several things."""

    key: str
    label: str
    event_type: str
    description: str
    link_path: str
    default: bool = True
    reasons: frozenset[str] | None = None

    def matches(self, event_type: str, data: dict) -> bool:
        return event_type == self.event_type and (self.reasons is None or data.get("reason") in self.reasons)


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


# --------------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------------


@dataclass
class Route:
    id: str
    integration_id: str
    action: str
    args: dict
    enabled: bool = True


@dataclass
class AlertSettings:
    types: dict[str, bool]
    """Each kind on or off (every kind is present; a kind missing from storage takes its default)."""
    email_enabled: bool
    recipients: list[str] | None
    """None: every super admin with an email address, as of when the alert is sent."""
    routes: list[Route]

    def enabled_kind(self, event_type: str, data: dict) -> AlertKind | None:
        return next((k for k in KINDS if self.types.get(k.key) and k.matches(event_type, data)), None)

    def as_stored(self) -> dict:
        return {
            "types": dict(self.types),
            "email": {"enabled": self.email_enabled, "recipients": self.recipients},
            "routes": [asdict(r) for r in self.routes],
        }


def load(session: Session) -> AlertSettings:
    stored = PlatformSettingsService(session).get(SETTINGS_KEY) or {}
    types = stored.get("types") or {}
    email = stored.get("email") or {}
    routes = []
    for raw in stored.get("routes") or []:
        try:
            routes.append(
                Route(
                    id=str(raw["id"]),
                    integration_id=str(raw["integration_id"]),
                    action=str(raw["action"]),
                    args=dict(raw.get("args") or {}),
                    enabled=bool(raw.get("enabled", True)),
                )
            )
        except (KeyError, TypeError):
            logger.warning(f"platform alerts: ignoring a malformed stored route: {raw!r}")
    recipients = email.get("recipients")
    return AlertSettings(
        types={k.key: bool(types.get(k.key, k.default)) for k in KINDS},
        email_enabled=bool(email.get("enabled", True)),
        recipients=list(recipients) if isinstance(recipients, list) else None,
        routes=routes,
    )


def statuses(session: Session) -> dict[str, dict]:
    return PlatformSettingsService(session).get(STATUS_KEY) or {}


def _record(session: Session, results: dict[str, dict]) -> None:
    """Merge channels' last deliveries into the status row (its own key: saving settings never races it)."""
    if not results:
        return
    try:
        service = PlatformSettingsService(session)
        current = service.get(STATUS_KEY) or {}
        service.set(STATUS_KEY, {**current, **results})
    except Exception:  # noqa: BLE001 — a status write must never break delivery
        session.rollback()
        logger.exception("platform alerts: could not record delivery status")


# --------------------------------------------------------------------------------------------------
# Where routes come from: the platform workspace's message-capable connections
# --------------------------------------------------------------------------------------------------


def _platform_workspace(session: Session):
    """The workspace whose integration connections platform alerts may use, or None.

    The platform workspace, found by its marker whatever it is called (services/group/platform_workspace)."""
    from marvin.services.group.platform_workspace import PlatformWorkspaceMissing, platform_workspace

    try:
        return platform_workspace(session)
    except PlatformWorkspaceMissing:
        return None


@dataclass
class Target:
    """A message-capable action on one connection in the platform workspace."""

    integration_id: str
    integration_name: str
    provider: str
    provider_name: str
    connection_enabled: bool
    action: Any  # alert_routing.MessageAction

    @property
    def key(self) -> tuple[str, str]:
        return (self.integration_id, self.action.key)


def targets(session: Session, workspace) -> list[Target]:
    """Every message-capable action on the platform workspace's connections whose provider is installed."""
    if workspace is None:
        return []
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return []
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.integrations import get_provider
    from marvin.services.integrations.alert_routing import message_actions

    found: list[Target] = []
    for row in session.query(IntegrationModel).filter(IntegrationModel.group_id == workspace.id).order_by(IntegrationModel.name).all():
        try:
            provider = get_provider(row.provider)
        except KeyError:
            continue  # not installed: nothing to run
        for action in message_actions(provider):
            found.append(
                Target(
                    integration_id=str(row.id),
                    integration_name=row.name,
                    provider=row.provider,
                    provider_name=getattr(provider, "name", row.provider),
                    connection_enabled=bool(row.enabled),
                    action=action,
                )
            )
    return found


# --------------------------------------------------------------------------------------------------
# Saving
# --------------------------------------------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ARG_TYPES = (str, int, float, bool)


class InvalidAlertSettings(ValueError):
    """What an admin asked for can't be saved; the message says why, for people."""


def _clean_recipients(recipients: list[str] | None) -> list[str] | None:
    if recipients is None:
        return None
    seen: dict[str, str] = {}
    for raw in recipients:
        addr = (raw or "").strip()
        if not addr:
            continue
        if not _EMAIL.match(addr):
            raise InvalidAlertSettings(f"'{addr}' isn't an email address.")
        seen.setdefault(addr.lower(), addr)
    if not seen:
        raise InvalidAlertSettings("Add at least one email address, or send to every super admin.")
    return list(seen.values())


def _clean_args(target: Target, args: dict | None) -> dict:
    """The admin's arguments for the action's own inputs (a channel…): the message fields are Marvin's;
    every required input present; plain values only. ``{{SECRET}}`` references stay as written."""
    action = target.action
    args = {k: v for k, v in (args or {}).items() if v is not None and v != ""}
    carried = {action.body_field, action.title_field} - {None}
    unknown = sorted(set(args) - set(action.inputs) - carried)
    if unknown:
        raise InvalidAlertSettings(f"{target.integration_name} → {action.label} takes no '{', '.join(unknown)}'.")
    missing = [k for k in action.required if k not in args]
    if missing:
        raise InvalidAlertSettings(f"{target.integration_name} → {action.label} needs {', '.join(missing)}.")
    bad = [k for k, v in args.items() if not isinstance(v, _ARG_TYPES)]
    if bad:
        raise InvalidAlertSettings(f"{target.integration_name} → {action.label}: {', '.join(bad)} must be plain text.")
    return {k: (v.strip() if isinstance(v, str) else v) for k, v in args.items() if k in action.inputs}


def validate(session: Session, *, types: dict[str, bool], email_enabled: bool, recipients: list[str] | None, routes: list[dict]) -> AlertSettings:
    """What the admin asked for as settings, or InvalidAlertSettings. Routes must name a message-capable
    action on a connection in the platform workspace."""
    unknown = sorted(set(types) - set(KINDS_BY_KEY))
    if unknown:
        raise InvalidAlertSettings(f"Unknown alert type: {', '.join(unknown)}.")
    current = load(session)
    cleaned_types = {k.key: bool(types.get(k.key, current.types[k.key])) for k in KINDS}

    workspace = _platform_workspace(session)
    if routes and workspace is None:
        raise InvalidAlertSettings("There's no platform workspace, so alerts can't go through an integration.")
    available = {t.key: t for t in targets(session, workspace)}
    existing_ids = {r.id for r in current.routes}
    cleaned: list[Route] = []
    seen: set[tuple] = set()
    for raw in routes:
        key = (str(raw.get("integration_id")), str(raw.get("action")))
        target = available.get(key)
        if target is None:
            raise InvalidAlertSettings(f"'{key[1]}' on connection {key[0]} can't carry alerts from the platform workspace.")
        args = _clean_args(target, raw.get("args"))
        same = (*key, tuple(sorted((k, str(v)) for k, v in args.items())))
        if same in seen:  # one action may serve several routes (two channels), but not twice the same one
            raise InvalidAlertSettings(f"{target.integration_name} → {target.action.label} is listed twice with the same settings.")
        seen.add(same)
        route_id = str(raw.get("id") or "")
        if route_id not in existing_ids or route_id in {r.id for r in cleaned}:
            route_id = str(uuid.uuid4())
        cleaned.append(Route(id=route_id, integration_id=key[0], action=key[1], args=args, enabled=bool(raw.get("enabled", True))))
    return AlertSettings(types=cleaned_types, email_enabled=bool(email_enabled), recipients=_clean_recipients(recipients), routes=cleaned)


def describe_changes(session: Session, old: AlertSettings, new: AlertSettings) -> list[str]:
    """What changed, for the audit event: kinds, email, routes by name. Never an argument's value."""
    changes = [f"{k.label}: {'on' if new.types[k.key] else 'off'}" for k in KINDS if old.types[k.key] != new.types[k.key]]
    if old.email_enabled != new.email_enabled:
        changes.append(f"Email: {'on' if new.email_enabled else 'off'}")
    if old.recipients != new.recipients:
        changes.append("Email recipients: " + ("every super admin" if new.recipients is None else f"{len(new.recipients)} address(es)"))
    names = {t.key: f"{t.integration_name} → {t.action.label}" for t in targets(session, _platform_workspace(session))}

    def name(route: Route) -> str:
        return names.get((route.integration_id, route.action), f"{route.integration_id} → {route.action}")

    before = {r.id: r for r in old.routes}
    after = {r.id: r for r in new.routes}
    changes += [f"Route removed: {name(r)}" for rid, r in before.items() if rid not in after]
    for rid, r in after.items():
        prev = before.get(rid)
        if prev is None:
            changes.append(f"Route added: {name(r)}" + ("" if r.enabled else " (off)"))
            continue
        if prev.enabled != r.enabled:
            changes.append(f"Route {name(r)}: {'on' if r.enabled else 'off'}")
        if prev.args != r.args:
            changes.append(f"Route {name(r)}: arguments changed")
    return changes


def save(session: Session, settings: AlertSettings) -> None:
    PlatformSettingsService(session).set(SETTINGS_KEY, settings.as_stored())


# --------------------------------------------------------------------------------------------------
# The message — one builder for every channel
# --------------------------------------------------------------------------------------------------


def _scrub(text: str | None) -> str:
    """No credentials: URL user info and any credential-like environment value, as backup errors are scrubbed."""
    from marvin.services.storage.healthcheck import scrub

    cleaned = scrub((text or "").strip(), os.environ) or ""
    return cleaned if len(cleaned) <= MAX_TEXT else cleaned[: MAX_TEXT - 1] + "…"


@dataclass
class AlertMessage:
    title: str
    summary: str
    reason: str
    link: str
    detail: str = ""
    scope: str = SCOPE

    @property
    def body(self) -> str:
        """The plain-text body a chat or notification channel gets (the title travels separately)."""
        lines = [self.summary]
        if self.detail:
            lines.append(self.detail)
        lines += [f"Scope: {self.scope}", self.reason, self.link]
        return "\n".join(line for line in lines if line)


def _ui_link(path: str) -> str:
    from marvin.services.ui_links import ui_link

    return ui_link(path)


def build_message(*, title: str, summary: str, reason: str, link_path: str, detail: str | None = None) -> AlertMessage:
    return AlertMessage(
        title=_scrub(title)[:200],
        summary=_scrub(summary),
        detail=_scrub(detail),
        reason=reason,
        link=_ui_link(link_path),
    )


def message_for(kind: AlertKind, event, data: dict) -> AlertMessage:
    """The alert for one platform event: its catalog title, its message, the backup error if there is one."""
    message = getattr(event, "message", None)
    title = getattr(message, "title", None) or kind.label
    summary = getattr(message, "body", None) or kind.description
    detail = data.get("error_message") if kind.event_type.startswith("backup_") else None
    return build_message(
        title=title,
        summary=summary,
        detail=detail,
        reason=f"Sent because “{kind.label}” alerts are on in Admin → Platform alerts.",
        link_path=kind.link_path,
    )


def trial_message(channel_label: str, by: str | None) -> AlertMessage:
    return build_message(
        title=TEST_TITLE,
        summary=f"This is a test of the {channel_label} route for platform alerts. Nothing is wrong.",
        reason="Sent from Admin → Platform alerts" + (f" by {by}." if by else "."),
        link_path=PAGE_PATH,
    )


# --------------------------------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------------------------------


@dataclass
class Delivery:
    outcome: str
    detail: str

    def status(self, event_type: str | None, test: bool) -> dict:
        return {"at": datetime.now(UTC).isoformat(), "outcome": self.outcome, "detail": self.detail[:500], "event_type": event_type, "test": test}


def super_admin_emails(session: Session) -> list[str]:
    from marvin.db.models.users.roles import PlatformRole
    from marvin.db.models.users.users import Users

    rows = session.query(Users.email).filter(Users.platform_role == PlatformRole.SUPER_ADMIN).order_by(Users.email).all()
    return [email for (email,) in rows if email]


def smtp_ready() -> bool:
    from marvin.core.config import get_app_settings

    return bool(get_app_settings().SMTP_ENABLED)


def _email_template(message: AlertMessage):
    from marvin.services.email.email_service import EmailTemplate

    esc = html.escape
    absolute = message.link.startswith(("http://", "https://"))
    top = esc(message.summary) + (f"<br><br>{esc(message.detail)}" if message.detail else "")
    bottom = f"Scope: {esc(message.scope)}<br>{esc(message.reason)}" + ("" if absolute else f"<br>{esc(message.link)}")
    return EmailTemplate(
        subject=message.title,
        header_text=esc(message.title),
        message_top=top,
        message_bottom=bottom,
        button_link=message.link if absolute else "",
        button_text="Open in Marvin" if absolute else "",
    )


def send_email(session: Session, settings: AlertSettings, message: AlertMessage) -> Delivery:
    """Email through the platform SMTP settings, to the explicit list or every super admin."""
    recipients = settings.recipients if settings.recipients is not None else super_admin_emails(session)
    if not recipients:
        return Delivery(SKIPPED, "No recipients: no super admin has an email address.")
    if not smtp_ready():
        return Delivery(SKIPPED, "Not sent: SMTP isn't configured (Admin → Email settings).")
    from marvin.services.email.email_service import EmailService

    service = EmailService()  # no workspace: the platform SMTP settings
    template = _email_template(message)
    failed: list[str] = []
    for addr in recipients:
        try:
            if not service.send_email(addr, template):
                failed.append(addr)
        except Exception as e:  # noqa: BLE001 — one address must not stop the rest
            logger.warning(f"platform alerts: email to {addr} failed: {e}")
            failed.append(addr)
    if failed:
        return Delivery(FAILED, f"Sent to {len(recipients) - len(failed)} of {len(recipients)}; failed: {', '.join(failed)}.")
    return Delivery(SENT, f"Sent to {len(recipients)} recipient(s).")


def send_route(session: Session, route: Route, message: AlertMessage, workspace=None) -> Delivery:
    """Run the route's action on its platform-workspace connection with the message filled in."""
    workspace = workspace if workspace is not None else _platform_workspace(session)
    if workspace is None:
        return Delivery(FAILED, "There's no platform workspace to send through.")
    target = next((t for t in targets(session, workspace) if t.key == (route.integration_id, route.action)), None)
    if target is None:
        return Delivery(
            FAILED, "The connection is gone from the platform workspace, its plugin isn't installed, or the action no longer sends messages."
        )
    if not target.connection_enabled:
        return Delivery(FAILED, f"{target.integration_name} is turned off in the platform workspace.")

    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.integrations import IntegrationContext, build_http, get_provider
    from marvin.services.integrations.arg_secrets import MissingSecretError, resolve_arg_secrets
    from marvin.services.integrations.errors import redact, secret_values
    from marvin.services.secrets.resolver import resolve_secret

    row = session.get(IntegrationModel, uuid.UUID(route.integration_id))
    provider = get_provider(row.provider)
    secret = None
    resolved: dict = {}
    try:
        secret = resolve_secret(row.secret_ref, workspace.id) if row.secret_ref else None
        resolved = resolve_arg_secrets(route.args, workspace.id)
        args = {**resolved, **target.action.args(message.title, message.body)}
        ctx = IntegrationContext(config=row.config or {}, secret=secret, logger=logger, http=build_http())
        provider.run_action(target.action.key, args, ctx)
    except MissingSecretError as e:
        return Delivery(FAILED, str(e))
    except Exception as e:  # noqa: BLE001 — a failing route is reported, never raised into the bus
        hidden = secret_values(secret, *(v for k, v in resolved.items() if route.args.get(k) != v))
        error = redact(str(e) or type(e).__name__, hidden)
        logger.warning(f"platform alerts: {target.integration_name} → {target.action.key} failed: {error}")
        return Delivery(FAILED, f"{target.integration_name} → {target.action.label} failed: {error}")
    return Delivery(SENT, f"Sent through {target.integration_name} → {target.action.label}.")


def _send(
    session: Session, settings: AlertSettings, message: AlertMessage, channels: list[str] | None, *, event_type: str | None, test: bool
) -> dict[str, dict]:
    """Send to each enabled channel (or the ones named), each isolated; record and return their statuses."""
    results: dict[str, dict] = {}
    if (settings.email_enabled and channels is None) or (channels is not None and EMAIL_CHANNEL in channels):
        try:
            delivery = send_email(session, settings, message)
        except Exception as e:  # noqa: BLE001
            logger.exception("platform alerts: email channel failed")
            delivery = Delivery(FAILED, f"Email failed: {_scrub(str(e))}")
        results[EMAIL_CHANNEL] = delivery.status(event_type, test)
    workspace = None
    for route in settings.routes:
        if (route.id not in channels) if channels is not None else not route.enabled:
            continue  # a named channel is sent even when off (the test button); otherwise only enabled ones
        workspace = workspace if workspace is not None else _platform_workspace(session)
        try:
            delivery = send_route(session, route, message, workspace)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"platform alerts: route {route.id} failed")
            delivery = Delivery(FAILED, f"Failed: {_scrub(str(e))}")
        results[route.id] = delivery.status(event_type, test)
    _record(session, results)
    return results


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
    return _send(session, settings, message_for(kind, event, data), None, event_type=event_type, test=False)


def send_test(session: Session, channel: str, by: str | None = None) -> dict:
    """Send the test message to one saved channel (``email`` or a route id), even when it's off."""
    settings = load(session)
    if channel == EMAIL_CHANNEL:
        label = "email"
    else:
        route = next((r for r in settings.routes if r.id == channel), None)
        if route is None:
            raise LookupError("No such route; save it first.")
        target = next((t for t in targets(session, _platform_workspace(session)) if t.key == (route.integration_id, route.action)), None)
        label = f"{target.integration_name} → {target.action.label}" if target else "integration"
    results = _send(session, settings, trial_message(label, by), [channel], event_type=None, test=True)
    return results.get(channel) or Delivery(FAILED, "Nothing was sent.").status(None, True)


def event_data(event) -> dict:
    """The event's payload as plain data (to match a kind's reason and read a backup error)."""
    document = getattr(event, "document_data", None)
    if document is None:
        return {}
    try:
        return document.model_dump(mode="json")
    except Exception:  # noqa: BLE001
        return {}
