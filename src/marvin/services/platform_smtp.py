"""The platform's SMTP server — the one mail goes through when no workspace profile applies (password resets,
platform alerts, the admin test email, and any workspace without an active SMTP profile of its own).

The environment (``SMTP_*``) is the baseline; Admin → Email edits override it **per field**, the way the security
policy does (services/platform_policy.py): every field an admin set wins, every field left unset falls back to the
environment. Nothing is "all or nothing" — an admin can change just the From address, or just the host.

Stored in ``platform_settings`` under ``smtp``: ``{host, port, username, auth_strategy, from_name, from_email,
password_ref}`` — only the fields an admin set. The password is a platform secret (``PLATFORM_SMTP_PASSWORD``,
services/secrets/platform.py), referenced by ``password_ref``; it is never returned by any API.

``effective()`` is the merged config and says where each field came from. The stored block and the password are cached
for a few seconds (they sit on every mail send); a save clears the cache. The environment is read fresh each call.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

KEY = "smtp"
PASSWORD_SLUG = "PLATFORM_SMTP_PASSWORD"
CACHE_SECONDS = 15

# field -> the AppSettings name that is its environment baseline
ENV_NAMES = {
    "host": "SMTP_HOST",
    "port": "SMTP_PORT",
    "username": "SMTP_USER",
    "auth_strategy": "SMTP_AUTH_STRATEGY",
    "from_name": "SMTP_FROM_NAME",
    "from_email": "SMTP_FROM_EMAIL",
}
FIELDS = tuple(ENV_NAMES)
STRATEGIES = ("TLS", "SSL", "NONE")
_EMAIL = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")

_cache: tuple[float, dict, str | None] | None = None
_lock = threading.Lock()


class SMTPSettingsError(ValueError):
    """A value that can't be saved (the message is safe to show)."""


@dataclass(frozen=True)
class SMTPConfig:
    """The SMTP server in force, merged field by field."""

    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    auth_strategy: str | None = None
    from_name: str | None = None
    from_email: str | None = None
    sources: dict[str, str | None] = field(default_factory=dict)
    """Per field (``password`` included): ``admin``, ``env`` or None (set nowhere)."""
    password_missing: bool = False
    """An admin password is on record but the secret backend can't produce it."""

    @property
    def ready(self) -> bool:
        return self.problem is None

    @property
    def problem(self) -> str | None:
        """What stops mail from going out, or None. The environment's rule: host, port, From and security are
        needed, and a TLS/SSL server also a username and password."""
        from marvin.core.settings.settings import AppSettings

        detail = AppSettings.validate_smtp(
            self.host, str(self.port) if self.port else None, self.from_name, self.from_email, self.auth_strategy, self.username, self.password
        )
        if detail.enabled:
            return None
        if self.password_missing and not self.password:
            return "The saved SMTP password is missing from the secret store — enter it again."
        return detail.description or "SMTP settings are incomplete."

    @property
    def source(self) -> str | None:
        """Overall: ``admin`` when an admin set any field, else ``env`` when the environment alone is complete, else None."""
        if "admin" in self.sources.values():
            return "admin"
        return "env" if self.ready else None

    @property
    def tls(self) -> bool:
        return (self.auth_strategy or "").upper() == "TLS"

    @property
    def ssl(self) -> bool:
        return (self.auth_strategy or "").upper() == "SSL"


# ── stored block ─────────────────────────────────────────────────────────────


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def _stored() -> tuple[dict, str | None]:
    """The admin's block and the admin password (None when none is set or it can't be read), cached."""
    global _cache
    with _lock:
        if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
            return _cache[1], _cache[2]
    try:
        from marvin.db.db_setup import session_context
        from marvin.services.platform_settings import PlatformSettingsService
        from marvin.services.secrets.platform import get_platform_secret

        with session_context() as session:
            block = dict(PlatformSettingsService(session).get(KEY) or {})
        password = get_platform_secret(block["password_ref"]) if block.get("password_ref") else None
    except Exception:  # noqa: BLE001 — no database (a script, a test without one): the environment decides
        block, password = {}, None
    with _lock:
        _cache = (time.monotonic(), block, password)
    return block, password


def _env(name: str) -> str | None:
    from marvin.core.config import get_app_settings

    value = getattr(get_app_settings(), name, None)
    if value is None:
        return None
    value = value.get_secret_value() if hasattr(value, "get_secret_value") else value
    return str(value) if str(value) != "" else None


def merge(block: dict, admin_password: str | None) -> SMTPConfig:
    """Merge an admin block over the environment, field by field."""
    values: dict[str, str | None] = {}
    sources: dict[str, str | None] = {}
    for name in FIELDS:
        admin = block.get(name)
        if admin not in (None, ""):
            values[name], sources[name] = str(admin), "admin"
        else:
            env = _env(ENV_NAMES[name])
            values[name], sources[name] = env, ("env" if env is not None else None)
    password_missing = bool(block.get("password_ref")) and admin_password is None
    if admin_password:
        password, sources["password"] = admin_password, "admin"
    else:
        password = _env("SMTP_PASSWORD")
        sources["password"] = "env" if password else None
    try:
        port = int(values["port"]) if values["port"] else None
    except ValueError:
        port = None
    return SMTPConfig(
        host=values["host"],
        port=port,
        username=values["username"],
        password=password,
        auth_strategy=(values["auth_strategy"] or "").upper() or None,
        from_name=values["from_name"],
        from_email=values["from_email"],
        sources=sources,
        password_missing=password_missing,
    )


def effective() -> SMTPConfig:
    """The SMTP server in force: each admin-set field, else the environment's."""
    block, password = _stored()
    return merge(block, password)


def ready() -> bool:
    return effective().ready


# ── saving ───────────────────────────────────────────────────────────────────


def _clean(values: dict) -> dict:
    """The admin block for what was asked, with each value checked; a blank value is unset, and a value equal to the
    environment's is stored as unset (the same rule as the security policy)."""
    clean: dict = {}
    for name in FIELDS:
        raw = values.get(name)
        text = " ".join(str(raw).split()) if raw not in (None, "") else ""
        if not text:
            continue
        if name == "host":
            if len(text) > 255 or " " in text or "/" in text:
                raise SMTPSettingsError("The host must be a server name or address, like smtp.example.com")
        elif name == "port":
            try:
                port = int(text)
            except ValueError as e:
                raise SMTPSettingsError("The port must be a whole number") from e
            if not 1 <= port <= 65535:
                raise SMTPSettingsError("The port must be between 1 and 65535")
            text = str(port)
        elif name == "auth_strategy":
            text = text.upper()
            if text not in STRATEGIES:
                raise SMTPSettingsError("Connection security must be TLS, SSL or None")
        elif name == "from_email":
            if not _EMAIL.match(text):
                raise SMTPSettingsError("The From address must be an email address")
            if len(text) > 254:
                raise SMTPSettingsError("The From address is too long")
        elif len(text) > (100 if name == "from_name" else 255):
            raise SMTPSettingsError(f"The {name.replace('_', ' ')} is too long")
        env = _env(ENV_NAMES[name]) or ""
        if text == (env.upper() if name == "auth_strategy" else env):
            continue
        clean[name] = int(text) if name == "port" else text
    return clean


def save(session, values: dict, *, password: str | None = None, clear_password: bool = False) -> SMTPConfig:
    """Replace the admin's fields with ``values`` (a blank or missing one goes back to the environment's). The password
    is left alone unless one is given (stored as a platform secret) or ``clear_password`` is set."""
    from marvin.services.platform_settings import PlatformSettingsService
    from marvin.services.secrets.platform import PlatformSecretReadOnly, delete_platform_secret, set_platform_secret

    svc = PlatformSettingsService(session)
    block = _clean(values)
    had_password = bool((svc.get(KEY) or {}).get("password_ref"))
    if password:
        if len(password) > 1000:
            raise SMTPSettingsError("The password is too long")
        try:
            set_platform_secret(PASSWORD_SLUG, password, session)
        except PlatformSecretReadOnly as e:
            raise SMTPSettingsError(f"This install's secret backend can't store a password: set {PASSWORD_SLUG} in the server's environment.") from e
        block["password_ref"] = PASSWORD_SLUG
    elif had_password and not clear_password:
        block["password_ref"] = PASSWORD_SLUG
    elif had_password:
        delete_platform_secret(PASSWORD_SLUG, session)
    svc.set(KEY, block)
    clear_cache()
    return effective()


def reset(session) -> SMTPConfig:
    """Back to the environment: every admin field and the admin password cleared."""
    from marvin.services.platform_settings import PlatformSettingsService
    from marvin.services.secrets.platform import delete_platform_secret

    svc = PlatformSettingsService(session)
    if svc.get(KEY):
        delete_platform_secret(PASSWORD_SLUG, session)
        svc.set(KEY, {})
    clear_cache()
    return effective()


def stored_block(session) -> dict:
    """The admin's block as saved (what differs from the environment), for the view and the audit."""
    from marvin.services.platform_settings import PlatformSettingsService

    return dict(PlatformSettingsService(session).get(KEY) or {})


def env_config() -> SMTPConfig:
    """What the environment alone would give — the baseline the admin's fields override."""
    return merge({}, None)


def env_summary(config: SMTPConfig) -> str | None:
    """A server in one line for the admin page, or None when there's no host."""
    if not config.host:
        return None
    parts = [f"{config.host}:{config.port}" if config.port else config.host, config.auth_strategy or "TLS"]
    if config.from_email:
        parts.append(f"{config.from_name} <{config.from_email}>" if config.from_name else config.from_email)
    return " · ".join(parts)


def describe_changes(before: dict, before_password: bool, after: dict, after_password: bool) -> list[str]:
    """What a save changed, for the audit line — field names and values, never the password."""
    changes = []
    for name in FIELDS:
        old, new = before.get(name), after.get(name)
        if old != new:
            label = name.replace("_", " ")
            changes.append(f"{label} set to {new}" if new not in (None, "") else f"{label} back to the environment's")
    if before_password != after_password:
        changes.append("password changed" if after_password else "password cleared")
    return changes
