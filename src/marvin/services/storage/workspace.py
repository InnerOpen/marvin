"""A workspace's own asset storage ("bring your own storage"): which bucket a workspace's new uploads go to, and the
provider for the rows already stored in one.

An asset row in a workspace's bucket records ``ws:<connection id>`` as its ``storage_provider``. The location points
at a connection (one bucket), not at the workspace: switching a workspace to another bucket leaves its old rows on
the old connection, still read with that connection's keys, and nothing moves unless asked.

Rules (tasks/byo-storage-plan.md, decided 2026-10-14):

- Off unless a platform admin allows it (platform setting ``workspace_storage``, else
  ``STORAGE_ALLOW_WORKSPACE_STORAGE``). Turned off after a workspace opted in, that workspace's uploads are refused
  rather than sent to the platform's bucket; reads keep working.
- A workspace in ``workspace`` mode never falls back to the platform's bucket: no verified connection, or one that
  can't be built, refuses the upload (``WorkspaceStorageUnavailable``, a 503 with a plain message).
- The provider is built from the connection's values only — non-secret settings on the row, keys from workspace
  secrets — never from Marvin's environment, and only for a plugin whose ``workspace_settings`` declaration is sound.
- The endpoint must pass the platform's endpoint policy (``known`` providers by default), and a connection can't name
  the platform's own bucket.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from marvin_integration_sdk.storage import StorageConfigError, read_config, workspace_settings_problems

from . import registry
from .provider_factory import WORKSPACE_LOCATION_PREFIX as LOCATION_PREFIX

logger = logging.getLogger(__name__)

POLICY_KEY = "workspace_storage"
ENDPOINT_POLICIES = ("known", "public", "any")
KNOWN_ENDPOINT_SUFFIXES = (".r2.cloudflarestorage.com", ".amazonaws.com", ".backblazeb2.com")
"""Hosts the ``known`` policy accepts: Cloudflare R2, AWS S3 and Backblaze B2. An empty endpoint (AWS's default) is
accepted too."""
ROW_TTL_SECONDS = 5.0
"""How long a read of a connection row is reused (every asset URL on a ``ws:`` row asks for its provider)."""
MODE_PLATFORM, MODE_WORKSPACE = "platform", "workspace"
STATUS_OK, STATUS_RETIRED = "ok", "retired"


class WorkspaceStorageUnavailable(Exception):
    """A workspace's own storage can't take an upload. The message is safe to show and never names a secret."""

    status_code = 503


@dataclass(frozen=True)
class Policy:
    allowed: bool
    endpoint_policy: str = "known"
    allowed_plugins: tuple[str, ...] = ("s3",)


@dataclass(frozen=True)
class WriteTarget:
    """Where a workspace's new uploads go: ``location`` None is the platform's storage."""

    location: str | None
    provider: Any


@dataclass(frozen=True)
class _Connection:
    """The parts of a connection row a provider is built from (a detached snapshot, safe to cache)."""

    id: str
    group_id: str
    plugin_slug: str
    settings: dict
    secret_refs: dict
    status: str
    version: int


_rows: dict[str, tuple[float, _Connection | None]] = {}
_providers: dict[tuple[str, int, str], Any] = {}
_lock = threading.Lock()


# ── locations ────────────────────────────────────────────────────────────────


def is_workspace_location(slug: str | None) -> bool:
    return isinstance(slug, str) and slug.startswith(LOCATION_PREFIX)


def location_for(connection_id: Any) -> str:
    return f"{LOCATION_PREFIX}{connection_id}"


def connection_id_of(location: str) -> str:
    raw = location[len(LOCATION_PREFIX) :]
    try:
        return str(uuid.UUID(raw))
    except ValueError as e:
        raise StorageConfigError(f"{location!r} is not a workspace storage location") from e


# ── policy ───────────────────────────────────────────────────────────────────


def policy(session) -> Policy:
    """The platform's policy: an admin's setting where there is one, else ``STORAGE_ALLOW_WORKSPACE_STORAGE`` (off)."""
    from marvin.core.config import get_app_settings
    from marvin.services.platform_settings import PlatformSettingsService

    stored = PlatformSettingsService(session).get(POLICY_KEY) or {}
    allowed = stored.get("allowed")
    endpoint = stored.get("endpoint_policy") if stored.get("endpoint_policy") in ENDPOINT_POLICIES else "known"
    plugins = tuple(stored.get("allowed_plugins") or ("s3",))
    return Policy(
        allowed=bool(allowed) if allowed is not None else bool(get_app_settings().STORAGE_ALLOW_WORKSPACE_STORAGE),
        endpoint_policy=endpoint,
        allowed_plugins=plugins,
    )


def check_endpoint(endpoint: str | None, endpoint_policy: str = "known", *, production: bool = True) -> None:
    """Raise ``StorageConfigError`` unless Marvin may connect to ``endpoint`` for a workspace under the policy."""
    if not endpoint:
        return  # the provider's default service (AWS S3)
    parts = urlsplit(str(endpoint).strip())
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or parts.scheme not in ("https", "http"):
        raise StorageConfigError("the endpoint must be an absolute https URL")
    if parts.scheme == "http" and production:
        raise StorageConfigError("the endpoint must use https")
    if endpoint_policy == "any":
        return
    if endpoint_policy == "known":
        if not host.endswith(KNOWN_ENDPOINT_SUFFIXES):
            raise StorageConfigError("the endpoint isn't a known storage service (Cloudflare R2, AWS S3 or Backblaze B2)")
        return
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)}
    except OSError as e:
        raise StorageConfigError("the endpoint's host doesn't resolve") from e
    if not addresses or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise StorageConfigError("the endpoint must resolve to public addresses only")


# ── connections and their providers ──────────────────────────────────────────


def _snapshot(row) -> _Connection:
    return _Connection(
        id=str(row.id),
        group_id=str(row.group_id),
        plugin_slug=row.plugin_slug,
        settings=dict(row.settings or {}),
        secret_refs=dict(row.secret_refs or {}),
        status=row.status,
        version=int(row.version or 1),
    )


def _load_connection(connection_id: str) -> _Connection | None:
    """The connection row, read through a short cache (no request session needed: reads come from URL building)."""
    now = time.monotonic()
    with _lock:
        hit = _rows.get(connection_id)
        if hit and hit[0] > now:
            return hit[1]
    from marvin.db.db_setup import session_context
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel

    with session_context() as session:
        row = session.get(WorkspaceStorageConnectionModel, uuid.UUID(connection_id))
        conn = _snapshot(row) if row is not None else None
    with _lock:
        _rows[connection_id] = (now + ROW_TTL_SECONDS, conn)
    return conn


def _platform_identity(provider_cls) -> tuple:
    """The platform's own (endpoint, bucket) for this plugin, to refuse a connection to the same bucket."""
    from marvin.core.config import get_app_settings

    return _identity(provider_cls, registry.settings_source(get_app_settings()).get)


def _identity(provider_cls, get) -> tuple:
    """What names a bucket: the endpoint plus the settings the provider always requires (its ``settings``, not its
    workspace ones), e.g. (R2 URL, bucket). Keys, the prefix and the public URL don't make it another bucket."""
    always = {s.env for s in provider_cls.settings if s.required and not s.secret}
    keys = [s.env for s in provider_cls.workspace_settings if s.env in always and s.env != provider_cls.endpoint_setting]
    endpoint = provider_cls.endpoint_setting
    return (str(get(endpoint) or "").rstrip("/").lower() if endpoint else "", *(str(get(k) or "") for k in keys))


def build_connection_provider(conn: _Connection, endpoint_policy: str, *, production: bool = True):
    """The provider for one connection, from its own values only. Raises ``StorageConfigError`` (never naming a
    secret's value) when the plugin can't serve workspace buckets, a key is missing or the endpoint isn't allowed."""
    from marvin.services.secrets.resolver import resolve_secret

    provider_cls = registry.get_plugin(conn.plugin_slug, needs="provider").provider
    if not provider_cls.workspace_settings:
        raise StorageConfigError(f"storage provider {conn.plugin_slug!r} doesn't support workspace buckets")
    if problems := workspace_settings_problems(provider_cls):
        raise StorageConfigError(f"storage provider {conn.plugin_slug!r} declares its workspace settings wrongly: {'; '.join(problems)}")
    declared = {s.env: s for s in provider_cls.workspace_settings}
    values = {env: v for env, v in conn.settings.items() if env in declared and not declared[env].secret}
    # Any setting may come from a workspace secret (an S3 access key ID isn't secret, but it belongs with its key);
    # a secret setting can only come from one, never from the plain settings above.
    for env, slug in conn.secret_refs.items():
        if env in declared and slug:
            values[env] = resolve_secret(str(slug), uuid.UUID(conn.group_id)) or ""
    check_endpoint(values.get(provider_cls.endpoint_setting) if provider_cls.endpoint_setting else None, endpoint_policy, production=production)
    config = read_config(provider_cls.workspace_settings, values)
    if _identity(provider_cls, config.get) == _platform_identity(provider_cls):
        raise StorageConfigError("a workspace connection can't use the platform's own bucket")
    return provider_cls.from_config(config)


def _production() -> bool:
    from marvin.core.config import get_app_settings

    return bool(get_app_settings().PRODUCTION)


def _cached_provider(conn: _Connection, endpoint_policy: str):
    key = (conn.id, conn.version, endpoint_policy)
    with _lock:
        if key in _providers:
            return _providers[key]
    provider = build_connection_provider(conn, endpoint_policy, production=_production())
    with _lock:
        for stale in [k for k in _providers if k[0] == conn.id and k != key]:
            del _providers[stale]
        _providers[key] = provider
    return provider


def provider_for_location(location: str, endpoint_policy: str | None = None):
    """The provider a ``ws:<connection id>`` row is read from: its connection, whatever its status (a retired or
    failing connection still serves the rows already in it). Raises ``StorageConfigError`` when it can't be built."""
    conn = _load_connection(connection_id_of(location))
    if conn is None:
        raise StorageConfigError(f"workspace storage connection {location!r} no longer exists")
    if endpoint_policy is None:
        from marvin.db.db_setup import session_context

        with session_context() as session:
            endpoint_policy = policy(session).endpoint_policy
    return _cached_provider(conn, endpoint_policy)


# ── where new uploads go ─────────────────────────────────────────────────────


def write_target(session, group_id) -> WriteTarget:
    """Where ``group_id``'s new uploads go: the platform's storage, or its own verified bucket. In ``workspace`` mode
    this never falls back to the platform: anything wrong raises ``WorkspaceStorageUnavailable``."""
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel, WorkspaceStorageSettingsModel
    from marvin.services.storage.provider_factory import get_storage_provider

    row = (
        session.query(WorkspaceStorageSettingsModel).filter(WorkspaceStorageSettingsModel.group_id == group_id).one_or_none()
        if group_id is not None
        else None
    )
    if row is None or row.credential_mode != MODE_WORKSPACE:
        return WriteTarget(None, get_storage_provider())
    pol = policy(session)
    if not pol.allowed:
        raise WorkspaceStorageUnavailable(
            "Uploads are paused: this workspace keeps its files in its own storage, which the platform has switched off. "
            "Ask a platform admin, or switch the workspace back to the platform's storage."
        )
    conn_row = session.get(WorkspaceStorageConnectionModel, row.active_connection_id) if row.active_connection_id else None
    if conn_row is None or conn_row.status != STATUS_OK:
        raise WorkspaceStorageUnavailable(
            "Uploads are paused: this workspace's own storage has no verified connection. Check the connection in Workspace settings → Storage."
        )
    if conn_row.plugin_slug not in pol.allowed_plugins:
        raise WorkspaceStorageUnavailable(f"Uploads are paused: the platform doesn't allow {conn_row.plugin_slug!r} for workspace storage.")
    conn = _snapshot(conn_row)
    try:
        provider = _cached_provider(conn, pol.endpoint_policy)
    except Exception as e:  # StorageConfigError, or the plugin failing to build its client
        logger.warning("workspace storage %s unavailable for uploads: %s", conn.id, e)
        raise WorkspaceStorageUnavailable(f"Uploads are paused: this workspace's own storage can't be reached ({e}).") from e
    return WriteTarget(location_for(conn.id), provider)


def reset_cache() -> None:
    """Forget cached connection rows and providers (tests, and after a connection is edited)."""
    with _lock:
        _rows.clear()
        _providers.clear()
