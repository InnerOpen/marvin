"""Resolve storage providers: the active one for new uploads, and the one each asset row lives in.

``STORAGE_PROVIDER`` names the provider new uploads go to. It resolves through the storage registry
(the built-in ``local``, plus installed plugins); an unknown slug is a configuration error that stops
startup (``validate_storage_config``), never a quiet fallback to local, which would hand out broken
asset URLs.

Reads go through ``provider_for(asset)``, which resolves the row's own ``storage_provider``. Rows on
different providers are served side by side, so switching ``STORAGE_PROVIDER`` (or moving assets
between providers) never breaks an existing asset.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from marvin_integration_sdk.storage import StorageConfigError, read_config

if TYPE_CHECKING:  # importing this module must not build settings (the backup CronJob imports the package)
    from marvin.core.settings.settings import AppSettings

from . import registry
from .base_provider import BaseStorageProvider
from .local_provider import LocalStorageProvider

# Providers for rows that aren't on the active provider, built once per (slug, settings object).
_row_providers: dict[tuple[str, int], BaseStorageProvider] = {}


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


def get_storage_provider(settings: "AppSettings | None" = None) -> BaseStorageProvider:
    """
    Get the configured storage provider (where new uploads go).

    Args:
        settings: Application settings. If None, uses the global settings.

    Returns:
        BaseStorageProvider instance configured based on settings

    Raises:
        StorageConfigError (a ValueError): if the provider is unknown or misconfigured
    """
    if settings is None:
        settings = _settings()
    return build_provider(getattr(settings, "STORAGE_PROVIDER", None) or registry.LOCAL, settings)


def provider_for(asset: Any) -> BaseStorageProvider:
    """The provider an asset row lives in (its ``storage_provider``), or a slug given directly.

    A row on the active provider gets ``get_storage_provider()`` (so tests that stand in for it keep
    working); a row on another one gets that provider, built once and reused.
    """
    slug = asset if isinstance(asset, str) else getattr(asset, "storage_provider", None)
    settings = _settings()
    if not slug or slug == (getattr(settings, "STORAGE_PROVIDER", None) or registry.LOCAL):
        return get_storage_provider()
    key = (slug, id(settings))
    if key not in _row_providers:
        _row_providers[key] = build_provider(slug, settings)
    return _row_providers[key]


def validate_storage_config(settings: "AppSettings | None" = None) -> BaseStorageProvider:
    """Startup check: the active provider must resolve and build. Raises ``StorageConfigError``
    with the reason (an unknown slug lists what is installed)."""
    return get_storage_provider(settings)


def reset_provider_cache() -> None:
    """Forget the providers built for rows (tests that change settings or plugins)."""
    _row_providers.clear()
