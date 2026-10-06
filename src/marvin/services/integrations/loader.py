"""Discover integration providers from installed plugin packages.

Marvin core ships with no built-in providers. Plugins are discovered via the ``marvin.integrations``
entry-point group — install a package that declares one and it registers on startup; uninstall it
and it's gone. Loading is resilient: a plugin that raises on import is logged and skipped, never
crashing startup. The loading itself is the shared plugin loader (services/plugin_loader.py).
"""

import importlib.metadata as importlib_metadata  # noqa: F401 — tests patch entry_points through this name

from marvin_integration_sdk import INTEGRATION_REGISTRY, register_provider

from marvin.services.plugin_loader import PluginLoadReport, load_entry_points

ENTRY_POINT_GROUP = "marvin.integrations"

ProviderLoadReport = PluginLoadReport
"""The integration name for the shared plugin load report (services/plugin_loader.py)."""

_reports: list[ProviderLoadReport] | None = None


def _register(ep) -> list[str]:
    before = set(INTEGRATION_REGISTRY)  # before import: a module may register on import (@register_provider)
    register_provider(ep.load())
    return sorted(set(INTEGRATION_REGISTRY) - before)


def _load_entry_points() -> list[ProviderLoadReport]:
    return load_entry_points(ENTRY_POINT_GROUP, _register, label="integration")


def load_providers(force: bool = False) -> list[ProviderLoadReport]:
    """Load installed plugins once (idempotent). Returns per-source load reports."""
    global _reports
    if _reports is not None and not force:
        return _reports
    _reports = _load_entry_points()
    # Read + validate every provider's logo once, here, so a refused one is logged at startup.
    from . import logos

    logos.prime(INTEGRATION_REGISTRY.values())
    return _reports
