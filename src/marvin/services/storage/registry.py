"""The storage plugins this platform has: the built-ins, plus whatever installed packages add.

The built-in ``local`` (disk provider + backup target) is always registered and is the mandatory
default; it can't be replaced. Installed packages add theirs through the ``marvin.storage_providers``
entry-point group, by slug. ``s3`` is registered from core only until the ``marvin-storage-s3`` plugin
takes over (it then replaces core's, and slice 7 of the storage plan removes core's copy).
"""

import logging
from collections.abc import Iterator, Mapping
from typing import Any

from marvin_integration_sdk.storage import ENTRY_POINT_GROUP, StorageConfigError, StoragePlugin

from marvin.services.plugin_loader import PluginLoadReport, load_entry_points, settings_source  # noqa: F401 — re-exported for callers

# Plain stdlib logging (Marvin configures the root logger at startup): importing this module must not
# build app settings or data directories, because the backup CronJob imports it too.
logger = logging.getLogger(__name__)

BUILTIN = "builtin"
LOCAL = "local"

_plugins: dict[str, StoragePlugin] = {}
_sources: dict[str, str] = {}  # slug → BUILTIN, or the entry-point name that added it
_reports: list[PluginLoadReport] | None = None


def _builtins() -> Iterator[tuple[StoragePlugin, str]]:
    from marvin.services.backup_engine.local_target import LocalBackupTarget

    from .local_provider import LocalStorageProvider

    # S3-compatible storage (R2, AWS, MinIO) is the marvin-storage-s3 plugin, baked into the image.
    yield StoragePlugin(slug=LOCAL, name="Local disk", provider=LocalStorageProvider, target=LocalBackupTarget), BUILTIN


def register(plugin: StoragePlugin, source: str) -> None:
    """Add a plugin under its slug. ``local`` is built in for good; any other clash is refused (the first
    one stays)."""
    current = _sources.get(plugin.slug)
    if current == BUILTIN:
        raise ValueError(f"storage slug {plugin.slug!r} is built in and can't be replaced")
    if current is not None:
        raise ValueError(f"storage slug {plugin.slug!r} is already provided by plugin '{current}'")
    _plugins[plugin.slug] = plugin
    _sources[plugin.slug] = source


def _register_entry_point(ep: Any) -> list[str]:
    exported = ep.load()
    plugin = exported if isinstance(exported, StoragePlugin) else exported() if callable(exported) else exported
    if not isinstance(plugin, StoragePlugin):
        raise TypeError(f"entry point must export a StoragePlugin (or a callable returning one), got {type(plugin).__name__}")
    register(plugin, ep.name)
    return [plugin.slug]


def load_plugins(force: bool = False) -> list[PluginLoadReport]:
    """Register the built-ins and every installed storage plugin, once. Returns the plugins' load
    reports (the built-ins aren't installed packages, so they have none)."""
    global _reports
    if _reports is not None and not force:
        return _reports
    _plugins.clear()
    _sources.clear()
    for plugin, source in _builtins():
        register(plugin, source)
    _reports = load_entry_points(ENTRY_POINT_GROUP, _register_entry_point, label="storage")
    return _reports


def plugins() -> Mapping[str, StoragePlugin]:
    load_plugins()
    return dict(_plugins)


def source_of(slug: str) -> str | None:
    load_plugins()
    return _sources.get(slug)


def get_plugin(slug: str, *, needs: str = "provider") -> StoragePlugin:
    """The plugin for ``slug``, which must offer ``needs`` ("provider" or "target"). Raises
    ``StorageConfigError`` saying what is installed, never a silent fallback."""
    load_plugins()
    plugin = _plugins.get(slug)
    offering = sorted(s for s, p in _plugins.items() if getattr(p, needs) is not None)
    what = "asset storage provider" if needs == "provider" else "backup target"
    if plugin is None:
        raise StorageConfigError(f"unknown {what} {slug!r}: no installed storage plugin provides it (available: {', '.join(offering)})")
    if getattr(plugin, needs) is None:
        raise StorageConfigError(f"storage plugin {slug!r} offers no {what} (available: {', '.join(offering)})")
    return plugin


def reset() -> None:
    """Forget what was loaded, so the next access loads again."""
    global _reports
    _reports = None
    _plugins.clear()
    _sources.clear()
