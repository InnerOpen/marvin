"""Platform alert channels: the connections platform alerts may send through — Admin → Alerts → Platform channels.

A workspace's integrations belong to that workspace; the admin area has none. These are the platform's own: a list
in ``platform_settings`` under ``platform_connections`` (``{"connections": [{id, provider, name, config, secret_ref,
enabled}]}``), each with its credential (for Apprise, the notification URLs) stored as a platform secret
(``PLATFORM_CONN_<id>``, services/secrets/platform.py), never returned by any API.

Any installed provider with a message action (``alert_routing.message_actions``) can be a platform channel;
Apprise is the one the page leads with. Alert routes (``platform_alerts``) name a connection by id and one of its
message actions, exactly as a workspace's routes name an integration.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field

from marvin.services.platform_settings import PlatformSettingsService
from marvin.services.secrets.platform import PlatformSecretReadOnly, delete_platform_secret, set_platform_secret

KEY = "platform_connections"
SECRET_PREFIX = "PLATFORM_CONN_"
FIRST_PROVIDER = "apprise"
"""Listed first: the page's primary way to add a channel."""
MAX_CONNECTIONS = 50


class PlatformConnectionError(ValueError):
    """What an admin asked for can't be saved; the message says why, for people."""


@dataclass
class PlatformConnection:
    id: str
    provider: str
    name: str
    config: dict = field(default_factory=dict)
    secret_ref: str | None = None
    enabled: bool = True

    def as_stored(self) -> dict:
        return asdict(self)


def secret_ref_for(connection_id: str) -> str:
    return f"{SECRET_PREFIX}{uuid.UUID(str(connection_id)).hex.upper()}"


def load(session) -> list[PlatformConnection]:
    stored = PlatformSettingsService(session).get(KEY) or {}
    found = []
    for raw in stored.get("connections") or []:
        try:
            found.append(
                PlatformConnection(
                    id=str(raw["id"]),
                    provider=str(raw["provider"]),
                    name=str(raw["name"]),
                    config=dict(raw.get("config") or {}),
                    secret_ref=raw.get("secret_ref") or None,
                    enabled=bool(raw.get("enabled", True)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # a malformed entry is skipped, never fatal to the alert path
    return found


def _store(session, items: list[PlatformConnection]) -> None:
    PlatformSettingsService(session).set(KEY, {"connections": [c.as_stored() for c in items]})


def get(session, connection_id: str) -> PlatformConnection | None:
    return next((c for c in load(session) if c.id == str(connection_id)), None)


# ── providers a channel can use ──────────────────────────────────────────────


def message_providers() -> list:
    """Installed providers with at least one message action, Apprise first, then by name."""
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return []
    from marvin.services.integrations import list_providers
    from marvin.services.integrations.alert_routing import message_actions

    found = [p for p in list_providers() if message_actions(p)]
    return sorted(found, key=lambda p: (p.slug != FIRST_PROVIDER, (getattr(p, "name", p.slug) or p.slug).lower()))


def _provider(slug: str):
    provider = next((p for p in message_providers() if p.slug == slug), None)
    if provider is None:
        raise PlatformConnectionError(f"'{slug}' isn't an installed plugin that can send messages.")
    return provider


def _check_config(provider, config: dict) -> dict:
    config = {k: v for k, v in (config or {}).items() if v not in (None, "")}
    required = (getattr(provider, "config_schema", None) or {}).get("required", [])
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise PlatformConnectionError(f"Missing required settings: {', '.join(missing)}.")
    return config


def _clean_name(items: list[PlatformConnection], name: str, keep_id: str | None = None) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise PlatformConnectionError("Give the channel a name.")
    if len(name) > 100:
        raise PlatformConnectionError("The name is too long.")
    if any(c.name.lower() == name.lower() and c.id != keep_id for c in items):
        raise PlatformConnectionError(f"There's already a channel called '{name}'.")
    return name


def _store_credential(session, ref: str, value: str) -> None:
    try:
        set_platform_secret(ref, value, session)
    except PlatformSecretReadOnly as e:
        raise PlatformConnectionError(f"This install's secret backend can't store a credential: set {ref} in the server's environment.") from e


# ── changes ──────────────────────────────────────────────────────────────────


def create(session, *, provider: str, name: str, config: dict | None = None, credential: str | None = None) -> PlatformConnection:
    items = load(session)
    if len(items) >= MAX_CONNECTIONS:
        raise PlatformConnectionError(f"At most {MAX_CONNECTIONS} platform channels.")
    prov = _provider(provider)
    clean_name = _clean_name(items, name)
    clean_config = _check_config(prov, config or {})
    needs = any(c.required for c in getattr(prov, "credentials", ()) or ())
    if needs and not (credential or "").strip():
        raise PlatformConnectionError(
            f"{getattr(prov, 'name', provider)} needs {(prov.credentials[0].label if prov.credentials else 'a credential')}."
        )
    conn = PlatformConnection(id=str(uuid.uuid4()), provider=provider, name=clean_name, config=clean_config)
    if (credential or "").strip():
        conn.secret_ref = secret_ref_for(conn.id)
        _store_credential(session, conn.secret_ref, credential.strip())
    _store(session, [*items, conn])
    return conn


def update(
    session, connection_id: str, *, name: str | None = None, enabled: bool | None = None, config: dict | None = None, credential: str | None = None
) -> PlatformConnection:
    items = load(session)
    conn = next((c for c in items if c.id == str(connection_id)), None)
    if conn is None:
        raise LookupError("No such channel.")
    if name is not None:
        conn.name = _clean_name(items, name, keep_id=conn.id)
    if enabled is not None:
        conn.enabled = bool(enabled)
    if config is not None:
        conn.config = _check_config(_provider(conn.provider), config)
    if credential is not None and credential.strip():
        conn.secret_ref = conn.secret_ref or secret_ref_for(conn.id)
        _store_credential(session, conn.secret_ref, credential.strip())
    _store(session, items)
    return conn


def delete(session, connection_id: str) -> PlatformConnection:
    items = load(session)
    conn = next((c for c in items if c.id == str(connection_id)), None)
    if conn is None:
        raise LookupError("No such channel.")
    rest = [c for c in items if c.id != conn.id]
    if conn.secret_ref and not any(c.secret_ref == conn.secret_ref for c in rest):  # a copy shared with another channel stays
        delete_platform_secret(conn.secret_ref, session)
    _store(session, rest)
    return conn
