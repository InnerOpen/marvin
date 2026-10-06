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

from marvin.services.plugin_loader import PluginLoadReport, load_entry_points

# Plain stdlib logging (Marvin configures the root logger at startup): importing this module must not
# build app settings or data directories, because the backup CronJob imports it too.
logger = logging.getLogger(__name__)

BUILTIN = "builtin"
CORE_TEMPORARY = "core"
LOCAL = "local"

_plugins: dict[str, StoragePlugin] = {}
_sources: dict[str, str] = {}  # slug → BUILTIN, CORE_TEMPORARY, or the entry-point name that added it
_reports: list[PluginLoadReport] | None = None


def _builtins() -> Iterator[tuple[StoragePlugin, str]]:
    from .local_provider import LocalStorageProvider
    from .s3_provider import S3StorageProvider

    yield StoragePlugin(slug=LOCAL, name="Local disk", provider=LocalStorageProvider), BUILTIN
    yield StoragePlugin(slug="s3", name="S3-compatible (core, until marvin-storage-s3)", provider=S3StorageProvider), CORE_TEMPORARY


def register(plugin: StoragePlugin, source: str) -> None:
    """Add a plugin under its slug. ``local`` is built in for good; core's temporary entries give way to
    an installed plugin with the same slug; any other clash is refused (the first one stays)."""
    current = _sources.get(plugin.slug)
    if current == BUILTIN:
        raise ValueError(f"storage slug {plugin.slug!r} is built in and can't be replaced")
    if current not in (None, CORE_TEMPORARY):
        raise ValueError(f"storage slug {plugin.slug!r} is already provided by plugin '{current}'")
    if current == CORE_TEMPORARY:
        logger.info(f"storage plugin '{source}' replaces core's built-in '{plugin.slug}'")
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


def settings_source(settings: Any) -> Mapping[str, Any]:
    """A read-only view for ``read_config``: Marvin's settings first, then the process environment
    (which already holds ``.env``), so a plugin can read variables core doesn't declare."""
    import os

    class _Source(Mapping):
        def __getitem__(self, key: str) -> Any:
            value = getattr(settings, key, None)
            if value is None:
                value = os.environ.get(key)
            if value is None:
                raise KeyError(key)
            return value

        def __iter__(self):
            return iter(())

        def __len__(self) -> int:
            return 0

    return _Source()


def reset() -> None:
    """Forget what was loaded, so the next access loads again."""
    global _reports
    _reports = None
    _plugins.clear()
    _sources.clear()
