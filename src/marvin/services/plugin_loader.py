"""Discover site-wide plugins from entry points, one group per plugin type.

Every plugin type (integrations: ``marvin.integrations``, storage: ``marvin.storage_providers``, AI
providers: ``marvin.ai_providers``) loads the same way: each entry point in the group is handed to that
type's register function, which loads it (``ep.load()``, so it can see what importing the module
registered) and returns the slugs it registered. Loading is resilient: a plugin that raises is logged
and skipped, never crashing startup, and every entry point leaves a report (distribution, version,
ok/error) for the admin Plugins page.
"""

import importlib.metadata as importlib_metadata
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# Plain stdlib logging (Marvin configures the root logger at startup): importing this module must not
# build app settings or data directories, because the backup CronJob imports it too.
logger = logging.getLogger(__name__)


@dataclass
class PluginLoadReport:
    """The outcome of loading one entry point (one plugin distribution can declare several)."""

    name: str  # entry-point name
    source: str  # "entry_point"
    ok: bool
    slugs: list[str] = field(default_factory=list)  # what this entry point registered
    distribution: str | None = None
    version: str | None = None
    error: str | None = None


def load_entry_points(group: str, register: Callable[[Any], Iterable[str]], *, label: str) -> list[PluginLoadReport]:
    """Hand every entry point in ``group`` to ``register`` (which loads and registers it).

    ``label`` names the plugin type in log lines ("integration", "storage"). A failure while loading or
    registering one entry point is recorded in its report and the rest carry on.
    """
    reports: list[PluginLoadReport] = []
    try:
        eps = importlib_metadata.entry_points(group=group)
    except Exception as e:  # noqa: BLE001 — metadata access should never take down the app
        logger.warning(f"could not read {label} entry points: {e}")
        return reports

    for ep in eps:
        dist = getattr(ep, "dist", None)
        dist_name = getattr(dist, "name", None)
        dist_version = getattr(dist, "version", None)
        try:
            slugs = sorted(register(ep))
            reports.append(PluginLoadReport(name=ep.name, source="entry_point", ok=True, slugs=slugs, distribution=dist_name, version=dist_version))
            logger.info(f"loaded {label} plugin '{ep.name}' ({dist_name} {dist_version}) → {slugs}")
        except Exception as e:  # noqa: BLE001 — one broken plugin must not block the others
            logger.warning(f"{label} plugin '{ep.name}' failed to load: {e}")
            reports.append(PluginLoadReport(name=ep.name, source="entry_point", ok=False, distribution=dist_name, version=dist_version, error=str(e)))
    return reports


def settings_source(settings: Any) -> Mapping[str, Any]:
    """A read-only view of a plugin's settings by name: Marvin's settings first, then the process
    environment (which already holds ``.env``), so a plugin can read variables core doesn't declare."""
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
