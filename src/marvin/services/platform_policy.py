"""Platform settings an admin edits in the UI that used to be environment-only: the security policy (sign-in
throttling, password and reset-link rules, session length), the branding of Marvin's emails, and the remote MCP
server's switch and token lifetimes.

Each is a row in `platform_settings`. A security or remote MCP value set there wins over the environment variable of
the same name; one not set falls back to it, so a fresh install behaves exactly as its env says. Reads are cached for a few
seconds — they sit on the sign-in path — and a save clears the cache.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

SECURITY_KEY = "security_policy"
EMAIL_BRANDING_KEY = "email_branding"
REMOTE_MCP_KEY = "remote_mcp"
CACHE_SECONDS = 15


@dataclass(frozen=True)
class SecurityField:
    key: str  # the AppSettings name it overrides
    label: str
    help: str
    unit: str
    minimum: int
    maximum: int


SECURITY_FIELDS: tuple[SecurityField, ...] = (
    SecurityField("SECURITY_PASSWORD_MIN_LENGTH", "Minimum password length", "Registration, resets and changes.", "characters", 6, 128),
    SecurityField("SECURITY_PASSWORD_RESET_TOKEN_MINUTES", "Reset link lifetime", "How long an emailed reset link works.", "minutes", 5, 1440),
    SecurityField("TOKEN_TIME", "Sign-in session length", "Before asking to sign in again.", "hours", 1, 24 * 90),
    SecurityField("SECURITY_MAX_LOGIN_ATTEMPTS", "Failed sign-ins before a lockout", "Per account, over the window below.", "attempts", 3, 50),
    SecurityField("SECURITY_LOGIN_LOCKOUT_MINUTES", "Lockout", "An account is refused this long.", "minutes", 1, 1440),
    SecurityField("SECURITY_LOGIN_LONG_LOCKOUT_MINUTES", "Longer lockout", "From twice the failures on.", "minutes", 1, 10080),
    SecurityField("SECURITY_LOGIN_IP_MAX_FAILURES", "Failed sign-ins per address", "From one address, any accounts.", "attempts", 5, 500),
    SecurityField("SECURITY_LOGIN_FAILURE_WINDOW_HOURS", "Failure counting window", "Failures older than this are forgotten.", "hours", 1, 168),
    SecurityField("SECURITY_PASSWORD_RESET_MAX_PER_HOUR", "Reset emails per address", "More are dropped silently.", "per hour", 1, 50),
    SecurityField("SECURITY_PASSWORD_RESET_IP_MAX_PER_HOUR", "Reset requests per client address", "From one client address.", "per hour", 1, 500),
)
_FIELDS = {f.key: f for f in SECURITY_FIELDS}

DEFAULT_BRANDING = {"product_name": "Marvin", "footer_text": "Sent by Marvin CMS", "accent_color": "#4f9c84"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


class PolicyError(ValueError):
    """A value that can't be saved (the message is safe to show)."""


def _stored(key: str) -> dict:
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        from marvin.db.db_setup import session_context
        from marvin.services.platform_settings import PlatformSettingsService

        with session_context() as session:
            value = PlatformSettingsService(session).get(key) or {}
    except Exception:  # noqa: BLE001 — no database (a script, a test without one): the environment decides
        value = {}
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ── security ─────────────────────────────────────────────────────────────────


def security(name: str) -> int:
    """The value in force for one security setting: the admin's, else the environment's."""
    from marvin.core.config import get_app_settings

    if name not in _FIELDS:
        raise KeyError(name)
    override = _stored(SECURITY_KEY).get(name)
    return int(override) if override is not None else int(getattr(get_app_settings(), name))


def security_view(session) -> list[dict]:
    """Every editable security setting: its value in force, the environment's, and whether an admin set it."""
    from marvin.core.config import get_app_settings
    from marvin.services.platform_settings import PlatformSettingsService

    stored = PlatformSettingsService(session).get(SECURITY_KEY) or {}
    env = get_app_settings()
    rows = []
    for f in SECURITY_FIELDS:
        default = int(getattr(env, f.key))
        value = stored.get(f.key)
        rows.append(
            {
                "key": f.key,
                "label": f.label,
                "help": f.help,
                "unit": f.unit,
                "min": f.minimum,
                "max": f.maximum,
                "default": default,
                "value": int(value) if value is not None else default,
                "overridden": value is not None,
            }
        )
    return rows


def save_security(session, values: dict) -> list[dict]:
    """Set (an int) or clear (None) admin values; a value equal to the environment's is stored as cleared."""
    from marvin.core.config import get_app_settings
    from marvin.services.platform_settings import PlatformSettingsService

    svc = PlatformSettingsService(session)
    stored = dict(svc.get(SECURITY_KEY) or {})
    env = get_app_settings()
    for key, raw in (values or {}).items():
        field = _FIELDS.get(key)
        if field is None:
            raise PolicyError(f"{key} is not an editable security setting")
        if raw is None or raw == "":
            stored.pop(key, None)
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError) as e:
            raise PolicyError(f"{field.label} must be a whole number") from e
        if not field.minimum <= value <= field.maximum:
            raise PolicyError(f"{field.label} must be between {field.minimum} and {field.maximum} {field.unit}")
        if value == int(getattr(env, key)):
            stored.pop(key, None)
        else:
            stored[key] = value
    svc.set(SECURITY_KEY, stored)
    clear_cache()
    return security_view(session)


# ── email branding ───────────────────────────────────────────────────────────


def email_branding() -> dict:
    """The product name, footer line and accent colour the branded email template shows."""
    stored = _stored(EMAIL_BRANDING_KEY)
    return {k: (stored.get(k) or v) for k, v in DEFAULT_BRANDING.items()}


def save_email_branding(session, values: dict) -> dict:
    from marvin.services.platform_settings import PlatformSettingsService

    PlatformSettingsService(session).set(EMAIL_BRANDING_KEY, clean_email_branding(values))
    clear_cache()
    return email_branding()


def clean_email_branding(values: dict | None) -> dict:
    """The set values of a branding form, checked and tidied; a blank one is left out so it falls back. Shared with the
    workspace's branding (services/email/branding.py). Raises PolicyError."""
    clean: dict = {}
    for key in DEFAULT_BRANDING:
        raw = (values or {}).get(key)
        text = " ".join(str(raw).split()) if raw not in (None, "") else ""
        if not text:
            continue
        if key == "accent_color":
            if not _HEX.match(text):
                raise PolicyError("The accent colour must be a hex colour like #4f9c84")
            text = text.lower()
        elif len(text) > (40 if key == "product_name" else 120):
            raise PolicyError(f"{'The product name' if key == 'product_name' else 'The footer'} is too long")
        clean[key] = text
    return clean


# ── remote MCP ───────────────────────────────────────────────────────────────

REMOTE_MCP_FIELDS: tuple[SecurityField, ...] = (
    SecurityField("MCP_ACCESS_TOKEN_MINUTES", "Access token lifetime", "A client refreshes it without asking.", "minutes", 5, 1440),
    SecurityField("MCP_REFRESH_TOKEN_DAYS", "Idle connection lifetime", "Unused this long, a connection must sign in again.", "days", 1, 365),
    SecurityField("MCP_GRANT_MAX_DAYS", "Longest connection", "However often it is used, then sign in again.", "days", 1, 730),
)
_MCP_FIELDS = {f.key: f for f in REMOTE_MCP_FIELDS}
MAX_EXTRA_REDIRECT_URIS = 20
_REDIRECT_URI = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?(/[^\s*]*)?\*?$")


@dataclass(frozen=True)
class RemoteMcpPolicy:
    enabled: bool
    """Switched on, and able to run: in PRODUCTION that also needs PUBLIC_API_URL (the OAuth issuer)."""
    access_token_minutes: int
    refresh_token_days: int
    grant_max_days: int
    extra_redirect_uris: tuple[str, ...]
    """Exact https redirect URIs, or `https://host/path*` prefixes, allowed on top of the built-in list."""
    allow_dynamic_registration: bool


def _mcp_unavailable_reason() -> str | None:
    """Why remote MCP can't be switched on here, or None."""
    from marvin.core.config import get_app_settings

    env = get_app_settings()
    if env.PRODUCTION and not env.PUBLIC_API_URL:
        return "PUBLIC_API_URL is not set (the chart's config.publicApiUrl): remote MCP needs the API's public address."
    return None


def _mcp_int(stored: dict, key: str) -> int:
    from marvin.core.config import get_app_settings

    value = stored.get(key)
    return int(value) if value is not None else int(getattr(get_app_settings(), key))


def remote_mcp() -> RemoteMcpPolicy:
    """The remote MCP policy in force: the admin's values, else the environment's."""
    from marvin.core.config import get_app_settings

    stored = _stored(REMOTE_MCP_KEY)
    switched_on = stored.get("enabled")
    if switched_on is None:
        switched_on = bool(get_app_settings().MCP_REMOTE_ENABLED)
    return RemoteMcpPolicy(
        enabled=bool(switched_on) and _mcp_unavailable_reason() is None,
        access_token_minutes=_mcp_int(stored, "MCP_ACCESS_TOKEN_MINUTES"),
        refresh_token_days=_mcp_int(stored, "MCP_REFRESH_TOKEN_DAYS"),
        grant_max_days=_mcp_int(stored, "MCP_GRANT_MAX_DAYS"),
        extra_redirect_uris=tuple(stored.get("extra_redirect_uris") or ()),
        allow_dynamic_registration=stored.get("allow_dynamic_registration", True) is not False,
    )


def remote_mcp_view(session) -> dict:
    """What the admin card shows: the switch, each lifetime with its environment default, the extra redirect URIs,
    and the issuer the metadata would name."""
    from marvin.core.config import get_app_settings
    from marvin.services.platform_settings import PlatformSettingsService

    stored = PlatformSettingsService(session).get(REMOTE_MCP_KEY) or {}
    env = get_app_settings()
    fields = []
    for f in REMOTE_MCP_FIELDS:
        default = int(getattr(env, f.key))
        value = stored.get(f.key)
        fields.append(
            {
                "key": f.key,
                "label": f.label,
                "help": f.help,
                "unit": f.unit,
                "min": f.minimum,
                "max": f.maximum,
                "default": default,
                "value": int(value) if value is not None else default,
                "overridden": value is not None,
            }
        )
    switched_on = stored.get("enabled")
    issuer = env.PUBLIC_API_URL or None
    return {
        "enabled": bool(env.MCP_REMOTE_ENABLED) if switched_on is None else bool(switched_on),
        "enabled_default": bool(env.MCP_REMOTE_ENABLED),
        "unavailable_reason": _mcp_unavailable_reason(),
        "issuer": issuer,
        "resource": f"{issuer}/mcp" if issuer else None,
        "fields": fields,
        "extra_redirect_uris": list(stored.get("extra_redirect_uris") or []),
        "allow_dynamic_registration": stored.get("allow_dynamic_registration", True) is not False,
    }


def save_remote_mcp(session, values: dict) -> dict:
    """Save the keys present in `values`: `enabled` (bool, or None for the environment's), the lifetimes (an int, or
    None for the environment's), `extra_redirect_uris` (a list) and `allow_dynamic_registration` (bool)."""
    from marvin.core.config import get_app_settings
    from marvin.services.platform_settings import PlatformSettingsService

    svc = PlatformSettingsService(session)
    stored = dict(svc.get(REMOTE_MCP_KEY) or {})
    env = get_app_settings()
    for key, raw in (values or {}).items():
        if key == "enabled":
            if raw is None or bool(raw) == bool(env.MCP_REMOTE_ENABLED):
                stored.pop("enabled", None)
            else:
                stored["enabled"] = bool(raw)
            if raw and (reason := _mcp_unavailable_reason()):
                raise PolicyError(reason)
        elif key == "allow_dynamic_registration":
            if raw is None or bool(raw):
                stored.pop(key, None)
            else:
                stored[key] = False
        elif key == "extra_redirect_uris":
            uris = [str(u).strip() for u in (raw or []) if str(u).strip()]
            if len(uris) > MAX_EXTRA_REDIRECT_URIS:
                raise PolicyError(f"At most {MAX_EXTRA_REDIRECT_URIS} extra redirect URIs")
            for uri in uris:
                if len(uri) > 500 or not _REDIRECT_URI.match(uri):
                    raise PolicyError(f"{uri} is not an https URI (a trailing * makes it a prefix)")
            if uris:
                stored[key] = list(dict.fromkeys(uris))
            else:
                stored.pop(key, None)
        elif key in _MCP_FIELDS:
            field = _MCP_FIELDS[key]
            if raw is None or raw == "":
                stored.pop(key, None)
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError) as e:
                raise PolicyError(f"{field.label} must be a whole number") from e
            if not field.minimum <= value <= field.maximum:
                raise PolicyError(f"{field.label} must be between {field.minimum} and {field.maximum} {field.unit}")
            if value == int(getattr(env, key)):
                stored.pop(key, None)
            else:
                stored[key] = value
        else:
            raise PolicyError(f"{key} is not a remote MCP setting")
    if _mcp_int(stored, "MCP_REFRESH_TOKEN_DAYS") > _mcp_int(stored, "MCP_GRANT_MAX_DAYS"):
        raise PolicyError("The idle connection lifetime can't be longer than the longest connection")
    svc.set(REMOTE_MCP_KEY, stored)
    clear_cache()
    return remote_mcp_view(session)
