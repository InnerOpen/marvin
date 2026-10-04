"""Discover integration providers from installed plugin packages.

Marvin core ships with no built-in providers. Plugins are discovered via the ``marvin.integrations``
entry-point group — install a package that declares one and it registers on startup; uninstall it
and it's gone. Loading is resilient: a plugin that raises on import is logged and skipped, never
crashing startup.
"""

import importlib.metadata as importlib_metadata
from dataclasses import dataclass, field

from marvin_integration_sdk import INTEGRATION_REGISTRY, register_provider

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

ENTRY_POINT_GROUP = "marvin.integrations"


@dataclass
class ProviderLoadReport:
    """The outcome of loading one source of providers (built-ins, or a plugin distribution)."""

    name: str  # entry-point name
    source: str  # "entry_point"
    ok: bool
    slugs: list[str] = field(default_factory=list)  # provider slugs this source registered
    distribution: str | None = None
    version: str | None = None
    error: str | None = None


_reports: list[ProviderLoadReport] | None = None


def _load_entry_points() -> list[ProviderLoadReport]:
    reports: list[ProviderLoadReport] = []
    try:
        eps = importlib_metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception as e:  # noqa: BLE001 — metadata access should never take down the app
        logger.warning(f"could not read integration entry points: {e}")
        return reports

    for ep in eps:
        before = set(INTEGRATION_REGISTRY)
        dist = getattr(ep, "dist", None)
        dist_name = getattr(dist, "name", None)
        dist_version = getattr(dist, "version", None)
        try:
            provider_cls = ep.load()
            register_provider(provider_cls)
            slugs = sorted(set(INTEGRATION_REGISTRY) - before)
            reports.append(ProviderLoadReport(name=ep.name, source="entry_point", ok=True, slugs=slugs, distribution=dist_name, version=dist_version))
            logger.info(f"loaded integration plugin '{ep.name}' ({dist_name} {dist_version}) → {slugs}")
        except Exception as e:  # noqa: BLE001 — one broken plugin must not block the others
            logger.warning(f"integration plugin '{ep.name}' failed to load: {e}")
            reports.append(
                ProviderLoadReport(name=ep.name, source="entry_point", ok=False, distribution=dist_name, version=dist_version, error=str(e))
            )
    return reports


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
