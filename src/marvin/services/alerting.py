"""Alerts past the bell, shared by every scope that sends them: the platform's (Admin → Platform alerts,
services/platform_alerts.py) and each workspace's (Settings → Automation → Notifications,
services/workspace_alerts.py).

A scope (:class:`AlertScope`) says what differs: its kinds of alert, where its settings and each channel's
last delivery are stored, whose integration connections its routes use, who "everyone" is for email and
which SMTP settings send it, and how its messages are worded. Everything else lives here, once:

  * **email** — built in and on by default: to everyone the scope names (every super admin; a workspace's
    owners and admins) unless an explicit list is set. Without SMTP nothing is sent, and the channel's last
    delivery says so;
  * **push** — built in, on by default, and only when the server has Web Push configured (VAPID): to the
    phones and browsers of everyone the scope names who turned push on and takes the scope's kind of push
    (Profile → Notifications; services/web_push.py). Without VAPID it isn't a channel at all;
  * **integration routes** — any action that can carry a message (``alert_routing.message_actions``: Slack's
    ``send_message``, Apprise's ``notify``, whatever a plugin declares — never a list of names) on a
    connection in the scope's workspace, with the action's own arguments (a channel…).

A channel may take only some kinds (``kinds``; None takes every kind that is on). One alert is one attempt
per channel, no retries: a channel that fails is logged and its "last delivery" shows why; it never stops
the others. Messages carry a title and summary, the scope, why they were sent and a link — scrubbed like a
backup error, never an event's raw payload.
"""

from __future__ import annotations

import html
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

EMAIL_CHANNEL = "email"
PUSH_CHANNEL = "push"
MAX_TEXT = 1500

SENT, FAILED, SKIPPED = "sent", "failed", "skipped"


@dataclass(frozen=True)
class AlertKind:
    """One kind of alert an admin turns on or off: an event type, narrowed by the event's ``reason`` where
    one event type means several things."""

    key: str
    label: str
    event_type: str
    description: str
    link_path: str
    default: bool = True
    reasons: frozenset[str] | None = None
    recovered_by: str | None = None
    """The event that ends this kind's incident, when the scope sends a "working again" note for it."""
    push: bool = True
    """False: the Push channel never takes it (people choose that push in their Profile instead)."""

    def matches(self, event_type: str, data: dict) -> bool:
        return event_type == self.event_type and (self.reasons is None or data.get("reason") in self.reasons)


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
    kinds: list[str] | None = None
    """The kinds it takes; None: every kind that is on."""

    def takes(self, kind: str) -> bool:
        return self.kinds is None or kind in self.kinds

    def as_stored(self) -> dict:
        stored = asdict(self)
        if self.kinds is None:
            stored.pop("kinds")
        return stored


@dataclass
class AlertSettings:
    types: dict[str, bool]
    """Each kind on or off (every kind is present; a kind missing from storage takes its default)."""
    email_enabled: bool
    recipients: list[str] | None
    """None: everyone the scope names (every super admin, a workspace's owners and admins), as of when the alert is sent."""
    routes: list[Route]
    email_kinds: list[str] | None = None
    """The kinds email takes; None: every kind that is on."""
    push_enabled: bool = True
    push_kinds: list[str] | None = None
    """The kinds push takes; None: every kind that is on."""
    catalog: tuple[AlertKind, ...] = field(default=(), repr=False, compare=False)

    def enabled_kind(self, event_type: str, data: dict) -> AlertKind | None:
        return next((k for k in self.catalog if self.types.get(k.key) and k.matches(event_type, data)), None)

    def channels_for(self, kind: str) -> list[str]:
        """The channels an alert of ``kind`` goes to now: email, push (when the server has Web Push), then each
        enabled route that takes it."""
        from marvin.services import web_push

        found = [EMAIL_CHANNEL] if self.email_enabled and (self.email_kinds is None or kind in self.email_kinds) else []
        pushable = all(k.push for k in self.catalog if k.key == kind)
        if pushable and self.push_enabled and (self.push_kinds is None or kind in self.push_kinds) and web_push.configured():
            found.append(PUSH_CHANNEL)
        return found + [r.id for r in self.routes if r.enabled and r.takes(kind)]

    def as_stored(self) -> dict:
        email: dict[str, Any] = {"enabled": self.email_enabled, "recipients": self.recipients}
        if self.email_kinds is not None:
            email["kinds"] = list(self.email_kinds)
        push: dict[str, Any] = {"enabled": self.push_enabled}
        if self.push_kinds is not None:
            push["kinds"] = list(self.push_kinds)
        return {"types": dict(self.types), "email": email, "push": push, "routes": [r.as_stored() for r in self.routes]}


class AlertScope:
    """What differs between one scope's alerts and another's. Subclasses fill in every attribute and method."""

    name: str
    """For logs: "platform alerts"."""
    kinds: tuple[AlertKind, ...]
    page: str
    """Where people change the settings, for messages: "Admin → Platform alerts"."""
    page_path: str
    test_title: str
    everyone: str
    """Who email goes to without a list: "every super admin"."""
    nobody: str
    """Why "everyone" can be no one: "no super admin has an email address"."""
    email_setup: str
    """What sends email, for "Not sent: …": "SMTP isn't configured (Admin → Email settings)"."""
    where: str
    """Whose connections routes use: "the platform workspace"."""
    per_channel_kinds: bool = False
    """Whether a channel may take only some kinds."""
    push_category: str
    """The kind of push (services/web_push.py CATEGORIES) a person takes to get this scope's alerts."""
    push_everyone: str
    """Who push goes to: "super admins who turned on push with “Platform alerts” in their Profile"."""

    @property
    def kinds_by_key(self) -> dict[str, AlertKind]:
        return {k.key: k for k in self.kinds}

    @property
    def event_types(self) -> frozenset[str]:
        return frozenset({k.event_type for k in self.kinds} | {k.recovered_by for k in self.kinds if k.recovered_by})

    def stored_settings(self, session: Session) -> dict | None:
        raise NotImplementedError

    def store_settings(self, session: Session, stored: dict) -> None:
        raise NotImplementedError

    def stored_status(self, session: Session) -> dict:
        raise NotImplementedError

    def store_status(self, session: Session, status: dict) -> None:
        raise NotImplementedError

    def workspace(self, session: Session):
        """The workspace whose connections routes use, or None."""
        raise NotImplementedError

    def default_recipients(self, session: Session) -> list[str]:
        raise NotImplementedError

    def email_ready(self, session: Session) -> bool:
        raise NotImplementedError

    def push_people(self, session: Session) -> list:
        """The user ids push may go to (each still needs a device and the scope's kind of push on)."""
        raise NotImplementedError

    def email_service(self):
        raise NotImplementedError

    def scope_label(self, session: Session) -> str:
        raise NotImplementedError

    def reason(self, kind: AlertKind) -> str:
        """Why an alert of ``kind`` was sent, for its message."""
        raise NotImplementedError

    def trial_summary(self, channel_label: str) -> str:
        raise NotImplementedError


def load(scope: AlertScope, session: Session) -> AlertSettings:
    stored = scope.stored_settings(session) or {}
    types = stored.get("types") or {}
    email = stored.get("email") or {}
    routes = []
    for raw in stored.get("routes") or []:
        try:
            kinds = raw.get("kinds")
            routes.append(
                Route(
                    id=str(raw["id"]),
                    integration_id=str(raw["integration_id"]),
                    action=str(raw["action"]),
                    args=dict(raw.get("args") or {}),
                    enabled=bool(raw.get("enabled", True)),
                    kinds=[str(k) for k in kinds] if isinstance(kinds, list) else None,
                )
            )
        except (KeyError, TypeError, AttributeError):
            logger.warning(f"{scope.name}: ignoring a malformed stored route: {raw!r}")
    recipients = email.get("recipients")
    email_kinds = email.get("kinds")
    push = stored.get("push") or {}
    push_kinds = push.get("kinds")
    return AlertSettings(
        types={k.key: bool(types.get(k.key, k.default)) for k in scope.kinds},
        email_enabled=bool(email.get("enabled", True)),
        recipients=list(recipients) if isinstance(recipients, list) else None,
        routes=routes,
        email_kinds=[str(k) for k in email_kinds] if isinstance(email_kinds, list) else None,
        push_enabled=bool(push.get("enabled", True)),
        push_kinds=[str(k) for k in push_kinds] if isinstance(push_kinds, list) else None,
        catalog=scope.kinds,
    )


def save(scope: AlertScope, session: Session, settings: AlertSettings) -> None:
    scope.store_settings(session, settings.as_stored())


def statuses(scope: AlertScope, session: Session) -> dict[str, dict]:
    return scope.stored_status(session) or {}


def _record(scope: AlertScope, session: Session, results: dict[str, dict]) -> None:
    """Merge channels' last deliveries into the scope's status (its own storage: saving settings never races it)."""
    if not results:
        return
    try:
        current = scope.stored_status(session) or {}
        scope.store_status(session, {**current, **results})
    except Exception:  # noqa: BLE001 — a status write must never break delivery
        session.rollback()
        logger.exception(f"{scope.name}: could not record delivery status")


# --------------------------------------------------------------------------------------------------
# Where routes go: the scope's workspace's message-capable connections
# --------------------------------------------------------------------------------------------------


@dataclass
class Target:
    """A message-capable action on one connection in the scope's workspace."""

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
    """Every message-capable action on the workspace's connections whose provider is installed."""
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


def route_problem(scope: AlertScope, workspace, target: Target | None) -> str | None:
    """Why a route can't send right now, or None."""
    if workspace is None:
        return f"There's no {scope.where.removeprefix('the ')} to send through."
    if target is None:
        return f"The connection is gone from {scope.where}, its plugin isn't installed, or the action no longer sends messages."
    if not target.connection_enabled:
        return f"{target.integration_name} is turned off in {scope.where}."
    return None


def route_label(target: Target | None, route: Route) -> str:
    return f"{target.integration_name} → {target.action.label}" if target else f"(missing connection) → {route.action}"


# --------------------------------------------------------------------------------------------------
# Saving
# --------------------------------------------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ARG_TYPES = (str, int, float, bool)


class InvalidAlertSettings(ValueError):
    """What an admin asked for can't be saved; the message says why, for people."""


def _clean_recipients(scope: AlertScope, recipients: list[str] | None) -> list[str] | None:
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
        raise InvalidAlertSettings(f"Add at least one email address, or send to {scope.everyone}.")
    return list(seen.values())


def _clean_kinds(scope: AlertScope, kinds, channel: str) -> list[str] | None:
    """A channel's kinds, in the scope's order; None (every kind) when the scope has no per-channel kinds."""
    if kinds is None or not scope.per_channel_kinds:
        return None
    wanted = {str(k) for k in kinds}
    unknown = sorted(wanted - set(scope.kinds_by_key))
    if unknown:
        raise InvalidAlertSettings(f"Unknown alert type: {', '.join(unknown)}.")
    if not wanted:
        raise InvalidAlertSettings(f"{channel} takes no kind of alert: choose at least one, or turn it off.")
    return [k.key for k in scope.kinds if k.key in wanted]


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


def validate(
    scope: AlertScope,
    session: Session,
    *,
    types: dict[str, bool],
    email_enabled: bool,
    recipients: list[str] | None,
    routes: list[dict],
    email_kinds: list[str] | None = None,
    push: dict | None = None,
) -> AlertSettings:
    """What the admin asked for as settings, or InvalidAlertSettings. Routes must name a message-capable
    action on a connection in the scope's workspace. ``push`` ({enabled, kinds}) left out keeps the current
    push settings."""
    unknown = sorted(set(types) - set(scope.kinds_by_key))
    if unknown:
        raise InvalidAlertSettings(f"Unknown alert type: {', '.join(unknown)}.")
    current = load(scope, session)
    cleaned_types = {k.key: bool(types.get(k.key, current.types[k.key])) for k in scope.kinds}

    workspace = scope.workspace(session)
    if routes and workspace is None:
        raise InvalidAlertSettings(f"There's no {scope.where.removeprefix('the ')}, so alerts can't go through an integration.")
    available = {t.key: t for t in targets(session, workspace)}
    existing_ids = {r.id for r in current.routes}
    cleaned: list[Route] = []
    seen: set[tuple] = set()
    for raw in routes:
        key = (str(raw.get("integration_id")), str(raw.get("action")))
        target = available.get(key)
        if target is None:
            raise InvalidAlertSettings(f"'{key[1]}' on connection {key[0]} can't carry alerts from {scope.where}.")
        args = _clean_args(target, raw.get("args"))
        same = (*key, tuple(sorted((k, str(v)) for k, v in args.items())))
        if same in seen:  # one action may serve several routes (two channels), but not twice the same one
            raise InvalidAlertSettings(f"{target.integration_name} → {target.action.label} is listed twice with the same settings.")
        seen.add(same)
        route_id = str(raw.get("id") or "")
        if route_id not in existing_ids or route_id in {r.id for r in cleaned}:
            route_id = str(uuid.uuid4())
        kinds = _clean_kinds(scope, raw.get("kinds"), f"{target.integration_name} → {target.action.label}")
        cleaned.append(Route(id=route_id, integration_id=key[0], action=key[1], args=args, enabled=bool(raw.get("enabled", True)), kinds=kinds))
    if push is None:
        push_enabled, push_kinds = current.push_enabled, current.push_kinds
    else:
        push_enabled, push_kinds = bool(push.get("enabled", True)), _clean_kinds(scope, push.get("kinds"), "Push")
    return AlertSettings(
        types=cleaned_types,
        email_enabled=bool(email_enabled),
        recipients=_clean_recipients(scope, recipients),
        routes=cleaned,
        email_kinds=_clean_kinds(scope, email_kinds, "Email"),
        push_enabled=push_enabled,
        push_kinds=push_kinds,
        catalog=scope.kinds,
    )


def _kinds_text(scope: AlertScope, kinds: list[str] | None) -> str:
    if kinds is None:
        return "every kind"
    by_key = scope.kinds_by_key
    return ", ".join(by_key[k].label for k in kinds if k in by_key) or "none"


def describe_changes(scope: AlertScope, session: Session, old: AlertSettings, new: AlertSettings) -> list[str]:
    """What changed, for the audit event: kinds, email, routes by name. Never an argument's value."""
    changes = [f"{k.label}: {'on' if new.types[k.key] else 'off'}" for k in scope.kinds if old.types[k.key] != new.types[k.key]]
    if old.email_enabled != new.email_enabled:
        changes.append(f"Email: {'on' if new.email_enabled else 'off'}")
    if old.recipients != new.recipients:
        changes.append("Email recipients: " + (scope.everyone if new.recipients is None else f"{len(new.recipients)} address(es)"))
    if old.email_kinds != new.email_kinds:
        changes.append(f"Email takes: {_kinds_text(scope, new.email_kinds)}")
    if old.push_enabled != new.push_enabled:
        changes.append(f"Push: {'on' if new.push_enabled else 'off'}")
    if old.push_kinds != new.push_kinds:
        changes.append(f"Push takes: {_kinds_text(scope, new.push_kinds)}")
    names = {t.key: f"{t.integration_name} → {t.action.label}" for t in targets(session, scope.workspace(session))}

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
        if prev.kinds != r.kinds:
            changes.append(f"Route {name(r)} takes: {_kinds_text(scope, r.kinds)}")
    return changes


# --------------------------------------------------------------------------------------------------
# The message — one builder for every channel
# --------------------------------------------------------------------------------------------------


def scrub(text: str | None) -> str:
    """No credentials: URL user info and any credential-like environment value, as backup errors are scrubbed."""
    from marvin.services.storage.healthcheck import scrub as scrub_credentials

    cleaned = scrub_credentials((text or "").strip(), os.environ) or ""
    return cleaned if len(cleaned) <= MAX_TEXT else cleaned[: MAX_TEXT - 1] + "…"


@dataclass
class AlertMessage:
    title: str
    summary: str
    reason: str
    link: str
    detail: str = ""
    scope: str = ""
    path: str = ""
    """The link as a path in the app (push opens it in the app; ``link`` is the absolute URL email carries)."""

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


def build_message(*, title: str, summary: str, reason: str, link_path: str, scope: str, detail: str | None = None) -> AlertMessage:
    return AlertMessage(
        title=scrub(title)[:200],
        summary=scrub(summary),
        detail=scrub(detail),
        reason=reason,
        link=_ui_link(link_path),
        scope=scope,
        path=link_path,
    )


def trial_message(scope: AlertScope, session: Session, channel_label: str, by: str | None) -> AlertMessage:
    return build_message(
        title=scope.test_title,
        summary=scope.trial_summary(channel_label),
        reason=f"Sent from {scope.page}" + (f" by {by}." if by else "."),
        link_path=scope.page_path,
        scope=scope.scope_label(session),
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


def send_email(scope: AlertScope, session: Session, settings: AlertSettings, message: AlertMessage) -> Delivery:
    """Email the explicit list, or everyone the scope names, through the scope's SMTP settings."""
    recipients = settings.recipients if settings.recipients is not None else scope.default_recipients(session)
    if not recipients:
        return Delivery(SKIPPED, f"No recipients: {scope.nobody}.")
    if not scope.email_ready(session):
        return Delivery(SKIPPED, f"Not sent: {scope.email_setup}.")
    service = scope.email_service()
    template = _email_template(message)
    failed: list[str] = []
    for addr in recipients:
        try:
            if not service.send_email(addr, template):
                failed.append(addr)
        except Exception as e:  # noqa: BLE001 — one address must not stop the rest
            logger.warning(f"{scope.name}: email to {addr} failed: {e}")
            failed.append(addr)
    if failed:
        return Delivery(FAILED, f"Sent to {len(recipients) - len(failed)} of {len(recipients)}; failed: {', '.join(failed)}.")
    return Delivery(SENT, f"Sent to {len(recipients)} recipient(s).")


def send_push(scope: AlertScope, session: Session, message: AlertMessage, *, test: bool = False) -> Delivery:
    """Push to the devices of everyone the scope names who turned push on and takes its kind of push."""
    from marvin.services import web_push

    if not web_push.configured():
        return Delivery(SKIPPED, "Not sent: Web Push isn't set up on this server (VAPID keys).")
    people = web_push.push_ready_users(session, scope.push_people(session), scope.push_category)
    if not people:
        return Delivery(SKIPPED, f"No one to send to yet: push goes to {scope.push_everyone}.")
    push = web_push.PushMessage(
        title=message.title, body=message.summary, url=message.path or message.link, tag="alert-test" if test else None, urgency="high"
    )
    if getattr(scope, "group_id", None):  # a workspace alert opens in its workspace; platform alerts are /admin
        push.workspace = str(scope.group_id)
    result = web_push.send_to_users(session, [u.id for u in people], scope.push_category, push)
    gone = f"; {result.removed} device(s) no longer subscribed were removed" if result.removed else ""
    if result.sent == 0:
        return Delivery(FAILED, f"Not delivered to any of {result.devices} device(s){gone}.")
    failed = f", {result.failed} failed" if result.failed else ""
    return Delivery(SENT, f"Sent to {result.sent} device(s) of {len(result.people)} person(s){failed}{gone}.")


def send_route(scope: AlertScope, session: Session, route: Route, message: AlertMessage, workspace=None) -> Delivery:
    """Run the route's action on its connection in the scope's workspace with the message filled in."""
    workspace = workspace if workspace is not None else scope.workspace(session)
    target = next((t for t in targets(session, workspace) if t.key == (route.integration_id, route.action)), None)
    problem = route_problem(scope, workspace, target)
    if problem:
        return Delivery(FAILED, problem)

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
        logger.warning(f"{scope.name}: {target.integration_name} → {target.action.key} failed: {error}")
        return Delivery(FAILED, f"{target.integration_name} → {target.action.label} failed: {error}")
    return Delivery(SENT, f"Sent through {target.integration_name} → {target.action.label}.")


def send(
    scope: AlertScope, session: Session, settings: AlertSettings, message: AlertMessage, channels: list[str], *, event_type: str | None, test: bool
) -> dict[str, dict]:
    """Send to each named channel (``email``, ``push`` or a route id) — a named route even when it's off —
    each isolated; record and return their statuses."""
    results: dict[str, dict] = {}
    if EMAIL_CHANNEL in channels:
        try:
            delivery = send_email(scope, session, settings, message)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"{scope.name}: email channel failed")
            delivery = Delivery(FAILED, f"Email failed: {scrub(str(e))}")
        results[EMAIL_CHANNEL] = delivery.status(event_type, test)
    if PUSH_CHANNEL in channels:
        try:
            delivery = send_push(scope, session, message, test=test)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"{scope.name}: push channel failed")
            delivery = Delivery(FAILED, f"Push failed: {scrub(str(e))}")
        results[PUSH_CHANNEL] = delivery.status(event_type, test)
    workspace = None
    for route in settings.routes:
        if route.id not in channels:
            continue
        workspace = workspace if workspace is not None else scope.workspace(session)
        try:
            delivery = send_route(scope, session, route, message, workspace)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"{scope.name}: route {route.id} failed")
            delivery = Delivery(FAILED, f"Failed: {scrub(str(e))}")
        results[route.id] = delivery.status(event_type, test)
    _record(scope, session, results)
    return results


def send_test(scope: AlertScope, session: Session, channel: str, by: str | None = None) -> dict:
    """Send the test message to one saved channel (``email``, ``push`` or a route id), even when it's off."""
    settings = load(scope, session)
    if channel == EMAIL_CHANNEL:
        label = "email"
    elif channel == PUSH_CHANNEL:
        label = "push"
    else:
        route = next((r for r in settings.routes if r.id == channel), None)
        if route is None:
            raise LookupError("No such route; save it first.")
        target = next((t for t in targets(session, scope.workspace(session)) if t.key == (route.integration_id, route.action)), None)
        label = f"{target.integration_name} → {target.action.label}" if target else "integration"
    results = send(scope, session, settings, trial_message(scope, session, label, by), [channel], event_type=None, test=True)
    return results.get(channel) or Delivery(FAILED, "Nothing was sent.").status(None, True)


def event_data(event) -> dict:
    """The event's payload as plain data (to match a kind's reason, read an error, name a subject)."""
    document = getattr(event, "document_data", None)
    if document is None:
        return {}
    try:
        return document.model_dump(mode="json")
    except Exception:  # noqa: BLE001
        return {}
