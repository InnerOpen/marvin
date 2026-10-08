"""Web Push for the admin app: who takes which kind of push, and sending it to their devices.

Off unless the operator set VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_SUBJECT (``configured()``); then a
signed-in user turns push on per browser or phone in Profile → Notifications, which stores the device's
subscription (``push_subscriptions``), and chooses the kinds they take (``users.push_preferences``, null takes
every kind on). What sends one is services/push_notifications.py (the bell's items that need a person, AI
approvals) and services/alerting.py (the Push channel of workspace notifications and platform alerts).

A message is small and carries no content beyond a title, one line and a same-origin link — the app shows
the rest after sign-in. Each device is one attempt with a short timeout: a device the push service says is
gone (404/410) is deleted, any other failure counts on it (``failure_count``, reset by the next success).
Nothing here ever raises into its caller.
"""

from __future__ import annotations

import ipaddress
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

TIMEOUT_S = 10
TTL_S = 24 * 60 * 60
"""How long a push service keeps a message for a device that's offline."""
MAX_TITLE = 120
MAX_BODY = 240
MAX_TAG = 64
GONE = (404, 410)


@dataclass(frozen=True)
class PushCategory:
    key: str
    label: str
    description: str
    super_admin_only: bool = False


ACTIVITY = "activity"
APPROVALS = "approvals"
WORKSPACE_ALERTS = "workspace_alerts"
PLATFORM_ALERTS = "platform_alerts"

CATEGORIES: tuple[PushCategory, ...] = (
    PushCategory(
        ACTIVITY,
        "Workspace activity",
        "What the bell flags for a person: a form submission, a scheduled publish that's waiting. For editors and above.",
    ),
    PushCategory(APPROVALS, "AI approvals", "An agent you asked is waiting for your OK before it acts."),
    PushCategory(
        WORKSPACE_ALERTS,
        "Workspace alerts",
        "Failures from Settings → Automation → Notifications (workflows, scheduled tasks, connections), for owners and admins.",
    ),
    PushCategory(PLATFORM_ALERTS, "Platform alerts", "Admin → Platform alerts, such as a failed backup.", super_admin_only=True),
)
CATEGORY_KEYS = frozenset(c.key for c in CATEGORIES)


# --------------------------------------------------------------------------------------------------
# Configuration and preferences
# --------------------------------------------------------------------------------------------------


def _settings():
    from marvin.core.config import get_app_settings

    return get_app_settings()


def configured() -> bool:
    """Web Push is set up on this server (all three VAPID settings)."""
    return bool(_settings().WEB_PUSH_ENABLED)


def public_key() -> str | None:
    if not configured():
        return None
    return (_settings().VAPID_PUBLIC_KEY or "").strip() or None


def _is_super_admin(user) -> bool:
    from marvin.db.models.users.roles import PlatformRole

    role = getattr(user, "platform_role", None)
    return role == PlatformRole.SUPER_ADMIN or getattr(role, "value", role) == "SUPER_ADMIN"


def categories_for(user) -> list[PushCategory]:
    """The kinds of push this user can take (platform alerts only for super admins)."""
    return [c for c in CATEGORIES if not c.super_admin_only or _is_super_admin(user)]


def preferences(user) -> dict[str, bool]:
    """Each kind the user can take → on/off (a kind they never chose is on)."""
    stored = getattr(user, "push_preferences", None) or {}
    return {c.key: bool(stored.get(c.key, True)) for c in categories_for(user)}


def takes(user, category: str) -> bool:
    return preferences(user).get(category, False)


def set_preferences(session: Session, user, chosen: dict[str, bool]) -> dict[str, bool]:
    """Save the kinds the user chose (unknown keys are ignored; a kind left out keeps its setting)."""
    current = preferences(user)
    for key, on in chosen.items():
        if key in current:
            current[key] = bool(on)
    user.push_preferences = current
    session.commit()
    return preferences(user)


# --------------------------------------------------------------------------------------------------
# The message
# --------------------------------------------------------------------------------------------------


def safe_path(url: str | None) -> str:
    """A same-origin path for the notification's link ("/x?y#z"); anything else (absolute URLs, "//host",
    backslashes, control characters) becomes "/". Absolute links to this app's own UI keep their path."""
    raw = (url or "").strip()
    if raw.startswith(("http://", "https://")):
        from marvin.services.ui_links import ui_base_url

        base = (ui_base_url() or "").rstrip("/")
        if not base or not raw.startswith(base + "/"):
            return "/"
        raw = raw[len(base) :]
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw or any(ord(ch) < 32 for ch in raw):
        return "/"
    return raw[:1000]


def _clip(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class PushMessage:
    title: str
    body: str = ""
    url: str = "/"
    tag: str | None = None
    """Notifications with the same tag replace each other on a device."""
    badge: int | None = None
    """An app-icon count to show, when the source has one."""
    urgency: str = "normal"
    """very-low | low | normal | high — how eagerly a phone wakes for it."""
    ttl: int = TTL_S

    def payload(self) -> str:
        data: dict = {"title": _clip(self.title, MAX_TITLE) or "Marvin", "body": _clip(self.body, MAX_BODY), "url": safe_path(self.url)}
        if self.tag:
            data["tag"] = _clip(self.tag, MAX_TAG)
        if isinstance(self.badge, int) and self.badge >= 0:
            data["badge"] = self.badge
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


# --------------------------------------------------------------------------------------------------
# Subscriptions
# --------------------------------------------------------------------------------------------------


class InvalidSubscription(ValueError):
    """The browser's subscription can't be used; the message says why."""


def endpoint_problem(endpoint: str) -> str | None:
    """Why the server mustn't post to this endpoint, or None. Push services are public https hosts; in
    production a private or loopback host is refused (the server would be posting to its own network)."""
    parsed = urlparse(endpoint or "")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and not _settings().PRODUCTION):
        return "A push endpoint must be an https URL."
    host = parsed.hostname
    if not host:
        return "A push endpoint needs a host."
    if _settings().PRODUCTION:
        from marvin.services.integrations.http_client import _host_is_public

        try:
            ip = ipaddress.ip_address(host)
            public = ip.is_global
        except ValueError:
            public = _host_is_public(host)
        if not public:
            return "A push endpoint must be a public host."
    return None


def device_label(user_agent: str | None) -> str:
    """ "Chrome on Android"-style name from a user agent, for the device list."""
    ua = user_agent or ""
    browsers = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
    browser = next((name for token, name in browsers if token in ua), "Browser")
    system = next(
        (
            name
            for token, name in (
                ("Android", "Android"),
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Windows", "Windows"),
                ("Mac OS X", "macOS"),
                ("CrOS", "ChromeOS"),
                ("Linux", "Linux"),
            )
            if token in ua
        ),
        None,
    )
    return f"{browser} on {system}" if system else browser


def subscribe(
    session: Session, user, *, endpoint: str, p256dh: str, auth: str, user_agent: str | None, label: str | None, replaces: str | None = None
):
    """Store this device's subscription for ``user`` (upsert by endpoint: a device someone else subscribed on
    becomes this user's). ``replaces`` is the endpoint the browser rotated away from, removed if it's theirs."""
    from marvin.db.models.users.push_subscriptions import PushSubscriptionModel

    problem = endpoint_problem(endpoint)
    if problem:
        raise InvalidSubscription(problem)
    if not p256dh.strip() or not auth.strip():
        raise InvalidSubscription("The subscription is missing its keys.")
    if replaces and replaces != endpoint:
        session.query(PushSubscriptionModel).filter_by(endpoint=replaces, user_id=user.id).delete(synchronize_session=False)
    row = session.query(PushSubscriptionModel).filter_by(endpoint=endpoint).first()
    if row is None:
        row = PushSubscriptionModel(session=session, endpoint=endpoint, user_id=user.id, p256dh=p256dh, auth=auth, failure_count=0)
        session.add(row)
    elif str(row.user_id) != str(user.id):
        row.user_id = user.id
        row.label = None
        row.last_used_at = row.last_success_at = None
        row.failure_count = 0
    row.p256dh, row.auth = p256dh.strip(), auth.strip()
    row.user_agent = (user_agent or "")[:512] or None
    row.label = (label or "").strip()[:120] or row.label or device_label(user_agent)
    session.commit()
    return row


def devices(session: Session, user_id) -> list:
    from marvin.db.models.users.push_subscriptions import PushSubscriptionModel

    return session.query(PushSubscriptionModel).filter_by(user_id=user_id).order_by(PushSubscriptionModel.created_at).all()


def unsubscribe(session: Session, user_id, *, subscription_id=None, endpoint: str | None = None) -> bool:
    """Remove one of the user's devices, by id or by endpoint. False when it isn't theirs (or is gone)."""
    from marvin.db.models.users.push_subscriptions import PushSubscriptionModel

    query = session.query(PushSubscriptionModel).filter(PushSubscriptionModel.user_id == user_id)
    if subscription_id is not None:
        query = query.filter(PushSubscriptionModel.id == subscription_id)
    elif endpoint:
        query = query.filter(PushSubscriptionModel.endpoint == endpoint)
    else:
        return False
    gone = query.delete(synchronize_session=False)
    session.commit()
    return bool(gone)


# --------------------------------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------------------------------


@dataclass
class SendResult:
    devices: int = 0
    sent: int = 0
    failed: int = 0
    removed: int = 0
    people: set[str] = field(default_factory=set)
    """Users at least one device reached."""

    def add(self, other: SendResult) -> None:
        self.devices += other.devices
        self.sent += other.sent
        self.failed += other.failed
        self.removed += other.removed
        self.people |= other.people


def _vapid():
    from py_vapid import Vapid

    return Vapid.from_string(private_key=(_settings().VAPID_PRIVATE_KEY or "").strip())


def _post(sub, data: str, message: PushMessage, vapid) -> int:
    """One device: the HTTP status the push service answered (201/202 on success)."""
    from pywebpush import WebPushException, webpush

    try:
        response = webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=data,
            vapid_private_key=vapid,
            vapid_claims={"sub": (_settings().VAPID_SUBJECT or "").strip()},  # fresh dict: webpush adds aud/exp to it
            ttl=message.ttl,
            headers={"Urgency": message.urgency},
            timeout=TIMEOUT_S,
        )
        return int(getattr(response, "status_code", 201) or 201)
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status is None:
            raise
        return int(status)


def send_to_subscriptions(session: Session, subscriptions: Iterable, message: PushMessage) -> SendResult:
    """Send ``message`` to each subscription, one attempt each; prune the gone, count the failures."""
    result = SendResult()
    subs = list(subscriptions)
    if not subs or not configured():
        return result
    try:
        vapid = _vapid()
    except Exception as e:  # noqa: BLE001 — a bad key is the operator's to fix; never the caller's error
        logger.error(f"Web Push: VAPID_PRIVATE_KEY can't be read ({type(e).__name__}); nothing sent")
        result.devices, result.failed = len(subs), len(subs)
        return result
    data = message.payload()
    now = datetime.now(UTC)
    for sub in subs:
        result.devices += 1
        problem = endpoint_problem(sub.endpoint)
        try:
            status = 0 if problem else _post(sub, data, message, vapid)
        except Exception as e:  # noqa: BLE001 — network errors, timeouts: count it and move on
            logger.warning(f"Web Push: send to a device of user {sub.user_id} failed: {type(e).__name__}")
            status = 0
        sub.last_used_at = now
        if 200 <= status < 300:
            sub.last_success_at = now
            sub.failure_count = 0
            result.sent += 1
            result.people.add(str(sub.user_id))
        elif status in GONE:
            session.delete(sub)
            result.removed += 1
        else:
            if problem:
                logger.warning(f"Web Push: not sending to a device of user {sub.user_id}: {problem}")
            elif status:
                logger.warning(f"Web Push: the push service answered {status} for a device of user {sub.user_id}")
            sub.failure_count = (sub.failure_count or 0) + 1
            result.failed += 1
    try:
        session.commit()
    except Exception:  # noqa: BLE001 — bookkeeping must never fail a send
        session.rollback()
        logger.exception("Web Push: could not record delivery")
    return result


def _uuids(values: Iterable) -> list[uuid.UUID]:
    return [uuid.UUID(v) for v in dict.fromkeys(str(v) for v in values if v)]


def send_to_users(session: Session, user_ids: Iterable, category: str, message: PushMessage) -> SendResult:
    """Send to every device of each user who takes ``category`` (one push per device)."""
    from marvin.db.models.users import Users
    from marvin.db.models.users.push_subscriptions import PushSubscriptionModel

    ids = _uuids(user_ids)
    if not ids or not configured():
        return SendResult()
    try:
        users = session.query(Users).filter(Users.id.in_(ids)).all()
        wanted = [u.id for u in users if takes(u, category)]
        if not wanted:
            return SendResult()
        subs = session.query(PushSubscriptionModel).filter(PushSubscriptionModel.user_id.in_(wanted)).all()
        return send_to_subscriptions(session, subs, message)
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception(f"Web Push: sending {category} failed")
        return SendResult()


def push_ready_users(session: Session, user_ids: Iterable, category: str) -> list:
    """Of these users, the ones with at least one device who take ``category`` — who a send would reach."""
    from marvin.db.models.users import Users
    from marvin.db.models.users.push_subscriptions import PushSubscriptionModel

    ids = _uuids(user_ids)
    if not ids:
        return []
    with_devices = {str(r[0]) for r in session.query(PushSubscriptionModel.user_id).filter(PushSubscriptionModel.user_id.in_(ids)).distinct().all()}
    users = session.query(Users).filter(Users.id.in_(ids)).all()
    return [u for u in users if str(u.id) in with_devices and takes(u, category)]


def workspace_member_ids(session: Session, group_id, min_role) -> list:
    """The workspace's members whose role is ``min_role`` or above (OWNER > ADMIN > EDITOR > AUTHOR > VIEWER)."""
    from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    floor = WORKSPACE_ROLE_HIERARCHY.get(min_role, 0)
    roles = [role for role, rank in WORKSPACE_ROLE_HIERARCHY.items() if rank >= floor]
    rows = session.query(WorkspaceMembers.user_id).filter(WorkspaceMembers.group_id == group_id, WorkspaceMembers.workspace_role.in_(roles)).all()
    return [r[0] for r in rows]


def super_admin_ids(session: Session) -> list:
    from marvin.db.models.users import Users
    from marvin.db.models.users.roles import PlatformRole

    return [r[0] for r in session.query(Users.id).filter(Users.platform_role == PlatformRole.SUPER_ADMIN).all()]
