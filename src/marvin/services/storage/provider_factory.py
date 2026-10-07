"""Resolve storage providers: the one new uploads go to, and the one each asset row lives in.

Where new uploads go is a platform admin's choice (Admin → Storage, stored in ``platform_settings``
under ``storage``), with ``STORAGE_PROVIDER`` as the default until an admin picks one. Both resolve
through the storage registry (the built-in ``local``, plus installed plugins). ``STORAGE_PROVIDER``
is the operator's configuration: an unknown slug stops startup (``validate_storage_config``). The
admin's choice is data: the API only accepts a provider that is installed and configured, and if it
stops being available later (the plugin is uninstalled, its Secret removed), new uploads fall back to
``STORAGE_PROVIDER`` with an error in the log and on the admin Storage page, instead of the app
refusing to start (which would lock the admin out of the page that fixes it). That fallback is safe
where a quiet fallback used to hand out broken URLs, because every new row records the provider it
was actually stored in.

Reads go through ``provider_for(asset)``, which resolves the row's own ``storage_provider``. Rows on
different providers are served side by side, so switching where uploads go (or moving assets between
providers, ``scripts/storage_migrate.py``) never breaks an existing asset.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from marvin_integration_sdk.storage import StorageConfigError, read_config

if TYPE_CHECKING:  # importing this module must not build settings (the backup CronJob imports the package)
    from marvin.core.settings.settings import AppSettings

from . import registry
from .base_provider import BaseStorageProvider
from .local_provider import LocalStorageProvider

logger = logging.getLogger(__name__)

UPLOAD_SETTING_KEY = "storage"
"""``platform_settings`` key of the admin's storage choice: ``{"upload_provider": "<slug>" | null}``."""
CHOICE_TTL_SECONDS = 5.0
"""How long a read of the admin's choice is reused: every asset URL asks which provider is active, so it
isn't read from the database each time. Saving a choice resets it in this process at once."""

# Providers other than STORAGE_PROVIDER's, built once per (slug, settings object): rows on them, and the chosen one.
_row_providers: dict[tuple[str, int], BaseStorageProvider] = {}
_choice: tuple[float, str | None] | None = None  # (expires at, slug) of the last read of the admin's choice
_fallback_warned: set[tuple[str, str]] = set()


def _settings() -> "AppSettings":
    from marvin.core import config

    return config.get_app_settings()


def _local_provider(settings: "AppSettings") -> LocalStorageProvider:
    root = getattr(settings, "STORAGE_LOCAL_ROOT", None)
    if root is None:
        # Default to {DATA_DIR}/assets directory
        from marvin.core.config import get_app_dirs

        root = get_app_dirs().ASSETS_DIR
    else:
        root = Path(root)

    public_url = getattr(settings, "STORAGE_LOCAL_PUBLIC_URL", "/assets")

    # STORAGE_LOCAL_PUBLIC_URL doubles as the static MOUNT path (see app.py), so it must stay a
    # "/..."-rooted path. To hand clients fully-qualified URLs — a CDN, a tunnel host, or a
    # decoupled frontend on another origin — set STORAGE_LOCAL_PUBLIC_BASE_URL; it overrides the
    # URL prefix only, while files still mount at STORAGE_LOCAL_PUBLIC_URL.
    public_base = getattr(settings, "STORAGE_LOCAL_PUBLIC_BASE_URL", None)
    if public_base:
        public_url = public_base
    elif not settings.PRODUCTION and not public_url.startswith("http"):
        # Dev: frontend (4321) and API (8080) are different origins, so prepend the API origin.
        public_url = f"http://localhost:{settings.API_PORT}{public_url}"

    return LocalStorageProvider(root=root, public_base_url=public_url)


def build_provider(slug: str, settings: "AppSettings") -> BaseStorageProvider:
    """Build the provider registered under ``slug`` from ``settings``. Raises ``StorageConfigError``
    when no installed plugin provides it or its settings are incomplete."""
    if slug == registry.LOCAL:
        return _local_provider(settings)
    provider_cls = registry.get_plugin(slug, needs="provider").provider
    try:
        config = read_config(provider_cls.settings, registry.settings_source(settings))
    except StorageConfigError as e:
        raise StorageConfigError(f"storage provider {slug!r}: {e}") from e
    return provider_cls.from_config(config)


def env_provider_slug(settings: "AppSettings | None" = None) -> str:
    """``STORAGE_PROVIDER``: the default for new uploads until an admin chooses one."""
    return getattr(settings or _settings(), "STORAGE_PROVIDER", None) or registry.LOCAL


def _read_choice() -> str | None:
    try:
        from marvin.db.db_setup import session_context
        from marvin.services.platform_settings import PlatformSettingsService

        with session_context() as session:
            value = PlatformSettingsService(session).get(UPLOAD_SETTING_KEY) or {}
    except Exception as e:  # no database yet (a script, startup before migrations): no choice
        logger.debug(f"storage: the admin's upload provider choice is unreadable ({e}); using STORAGE_PROVIDER")
        return None
    slug = value.get("upload_provider") if isinstance(value, dict) else None
    return slug if isinstance(slug, str) and slug else None


def chosen_upload_provider() -> str | None:
    """The provider a platform admin chose for new uploads, or None (follow ``STORAGE_PROVIDER``)."""
    global _choice
    now = time.monotonic()
    if _choice is None or _choice[0] <= now:
        _choice = (now + CHOICE_TTL_SECONDS, _read_choice())
    return _choice[1]


def save_upload_choice(session, slug: str | None) -> None:
    """Store the admin's choice (None = follow ``STORAGE_PROVIDER``) and use it from now on. The caller
    checks the provider is available first (services/storage/admin.py)."""
    from marvin.services.platform_settings import PlatformSettingsService

    PlatformSettingsService(session).set(UPLOAD_SETTING_KEY, {"upload_provider": slug})
    reset_upload_choice()


@dataclass(frozen=True)
class UploadTarget:
    """Where new uploads go, and why."""

    env_default: str
    """``STORAGE_PROVIDER``."""
    chosen: str | None
    """The admin's choice, None when there is none."""
    effective: str
    """Where new uploads actually go: the choice, or ``env_default`` when there is none or it is unavailable."""
    error: str | None = None
    """Why the choice isn't used (the provider is no longer installed or configured)."""


def upload_target(settings: "AppSettings | None" = None) -> UploadTarget:
    settings = settings or _settings()
    env = env_provider_slug(settings)
    chosen = chosen_upload_provider()
    if not chosen or chosen == env:
        return UploadTarget(env, chosen, env)
    try:
        _provider(chosen, settings)
    except Exception as e:  # StorageConfigError, or a plugin failing to build its client
        reason = str(e) or type(e).__name__
        if (chosen, reason) not in _fallback_warned:
            _fallback_warned.add((chosen, reason))
            logger.error(f"storage: new uploads should go to {chosen!r} (Admin → Storage), but it is unavailable: {reason}; using {env!r} instead")
        return UploadTarget(env, chosen, env, reason)
    return UploadTarget(env, chosen, chosen)


def _provider(slug: str, settings: "AppSettings") -> BaseStorageProvider:
    """``slug``'s provider, built once per settings object and reused."""
    key = (slug, id(settings))
    if key not in _row_providers:
        _row_providers[key] = build_provider(slug, settings)
    return _row_providers[key]


def get_storage_provider(settings: "AppSettings | None" = None) -> BaseStorageProvider:
    """
    The provider new uploads go to: the admin's choice, else ``STORAGE_PROVIDER`` (see ``upload_target``).

    Args:
        settings: Application settings. If None, uses the global settings.

    Raises:
        StorageConfigError (a ValueError): if ``STORAGE_PROVIDER`` is unknown or misconfigured
    """
    if settings is None:
        settings = _settings()
    target = upload_target(settings)
    if target.effective == target.env_default:
        return build_provider(target.env_default, settings)
    return _provider(target.effective, settings)


def provider_for(asset: Any) -> BaseStorageProvider:
    """The provider an asset row lives in (its ``storage_provider``), or a slug given directly.

    A row on the provider uploads go to gets ``get_storage_provider()`` (so tests that stand in for it
    keep working); a row on another one gets that provider, built once and reused.
    """
    slug = asset if isinstance(asset, str) else getattr(asset, "storage_provider", None)
    settings = _settings()
    if not slug or slug == upload_target(settings).effective:
        return get_storage_provider()
    return _provider(slug, settings)


# --------------------------------------------------------------------------------------------------
# Public URLs, with a workspace's own public domain
# --------------------------------------------------------------------------------------------------

PUBLIC_URL_SETTING = "STORAGE_REMOTE_PUBLIC_URL"
"""The setting a remote provider builds its public URLs from. A provider that declares it can serve a
workspace from that workspace's own domain (``groups.asset_public_base_url``)."""
_domains: tuple[float, dict[str, str]] | None = None  # (expires at, {workspace id: public base URL})
_domain_providers: dict[tuple[str, str, int], BaseStorageProvider] = {}
_domain_warned: set[tuple[str, str]] = set()


def _read_workspace_public_bases() -> dict[str, str]:
    try:
        from marvin.db.db_setup import session_context
        from marvin.db.models.groups import Groups

        with session_context() as session:
            rows = session.query(Groups.id, Groups.asset_public_base_url).filter(Groups.asset_public_base_url.isnot(None)).all()
    except Exception as e:  # no database yet (a script, startup): the providers' own URLs
        logger.debug(f"storage: workspaces' public domains are unreadable ({e})")
        return {}
    return {str(gid): url for gid, url in rows if url}


def workspace_public_bases() -> dict[str, str]:
    """{workspace id: public base URL} of the workspaces a platform admin gave their own domain. Read
    through a short cache like the upload choice (every asset URL asks); saving one resets it here."""
    global _domains
    now = time.monotonic()
    if _domains is None or _domains[0] <= now:
        _domains = (now + CHOICE_TTL_SECONDS, _read_workspace_public_bases())
    return _domains[1]


def reset_workspace_public_bases() -> None:
    global _domains
    _domains = None


def supports_public_base(slug: str) -> bool:
    """Whether ``slug``'s provider builds URLs from ``STORAGE_REMOTE_PUBLIC_URL`` (so a workspace domain applies)."""
    if slug == registry.LOCAL:
        return False
    try:
        provider_cls = registry.get_plugin(slug, needs="provider").provider
    except StorageConfigError:
        return False
    return any(s.env == PUBLIC_URL_SETTING for s in getattr(provider_cls, "settings", ()))


def _provider_with_public_base(slug: str, base: str, settings: "AppSettings") -> BaseStorageProvider:
    """``slug``'s provider built from the same settings, except ``STORAGE_REMOTE_PUBLIC_URL`` = ``base``:
    the same bucket and credentials, URLs on the workspace's domain. Built once per (slug, base)."""
    cache_key = (slug, base, id(settings))
    if cache_key not in _domain_providers:
        if not supports_public_base(slug):
            raise StorageConfigError(f"storage provider {slug!r} has no {PUBLIC_URL_SETTING} setting, so it can't serve a workspace's own domain")
        provider_cls = registry.get_plugin(slug, needs="provider").provider
        source = registry.settings_source(settings)

        class _WithBase(dict):
            def get(self, key, default=None):  # read_config only calls get()
                return base if key == PUBLIC_URL_SETTING else (source[key] if key in source else default)

        try:
            config = read_config(provider_cls.settings, _WithBase())
        except StorageConfigError as e:
            raise StorageConfigError(f"storage provider {slug!r}: {e}") from e
        _domain_providers[cache_key] = provider_cls.from_config(config)
    return _domain_providers[cache_key]


def public_url_for(slug: str | None, storage_key: str, group_id: Any = None, provider: BaseStorageProvider | None = None) -> str:
    """The URL a file is served at: ``slug``'s provider (``provider`` when the caller has it already),
    on the workspace's own public domain when a platform admin set one and the provider is a remote one
    that builds URLs from ``STORAGE_REMOTE_PUBLIC_URL``. Local files always use the API host. If the
    domain can't be applied (the provider has no such setting, or fails to build), the provider's own
    URL is used and the reason logged once."""
    base = workspace_public_bases().get(str(group_id)) if group_id is not None and slug and slug != registry.LOCAL else None
    if base:
        try:
            return _provider_with_public_base(slug, base, _settings()).get_public_url(storage_key)
        except Exception as e:
            reason = str(e) or type(e).__name__
            if (slug, reason) not in _domain_warned:
                _domain_warned.add((slug, reason))
                logger.error(f"storage: workspace {group_id} should be served from {base}, but {reason}; using the provider's own URL")
    return (provider or provider_for(slug)).get_public_url(storage_key)


def asset_public_url(asset: Any) -> str:
    """The URL an asset row (or anything with ``storage_provider``, ``storage_key`` and ``group_id``) is served at."""
    group_id = getattr(asset, "group_id", None) or getattr(asset, "_group_id", None)  # a row, or an AssetRead made from one
    return public_url_for(getattr(asset, "storage_provider", None), asset.storage_key, group_id)


def provider_slug(provider: BaseStorageProvider) -> str:
    """The slug a provider instance stores rows under: its own ``slug``, else a guess from its class
    name (stand-ins in tests)."""
    slug = getattr(provider, "slug", "")
    if slug and isinstance(slug, str):
        return slug
    name = type(provider).__name__
    return registry.LOCAL if "Local" in name else "s3" if "S3" in name else "unknown"


def validate_storage_config(settings: "AppSettings | None" = None) -> BaseStorageProvider:
    """Startup check: ``STORAGE_PROVIDER`` must resolve and build. Raises ``StorageConfigError`` with
    the reason (an unknown slug lists what is installed). The admin's choice isn't checked here: an
    unavailable one falls back (``upload_target``) rather than stopping the app."""
    settings = settings or _settings()
    return build_provider(env_provider_slug(settings), settings)


def reset_upload_choice() -> None:
    """Read the admin's choice from the database again on next use."""
    global _choice
    _choice = None


def reset_provider_cache() -> None:
    """Forget the providers built for rows and the admin's choice (tests that change settings or plugins)."""
    _row_providers.clear()
    _fallback_warned.clear()
    _domain_providers.clear()
    _domain_warned.clear()
    reset_upload_choice()
    reset_workspace_public_bases()
